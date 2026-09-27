"""Pieces shared by the clean_*.py scripts: reading raw files, logging dropped rows,
time columns, and the bus/streetcar cleaner (both use the same layout)."""

import logging
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from transitquery.etl.normalize import (
    combine_datetime,
    normalize_bound,
    normalize_delay,
    normalize_incident,
    normalize_location,
    normalize_route,
    normalize_vehicle,
)

logger = logging.getLogger(__name__)

# Resolved from this file (src/transitquery/etl/common.py -> project root), not the
# current folder, so it works from the terminal, a notebook in notebooks/, or tests.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
MIN_YEAR = 2014          # all published years; raise it to keep less history
TIMEZONE = "America/Toronto"


# --- Reading ------------------------------------------------------------------------

def _latest_year_in_name(name: str) -> int | None:
    """'ttc-bus-delay-data-2019.xlsx' -> 2019, 'jan-2014-april-2017' -> 2017,
    'since-2025' -> None (open-ended, always read)."""
    if "since" in name:
        return None
    years = [int(y) for y in re.findall(r"20\d{2}", name)]
    return max(years) if years else None


def read_raw(dataset: str, min_year: int = MIN_YEAR, skip_files: tuple[str, ...] = (),
             raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Read every delay file of one dataset (all Excel sheets + the CSV) into one frame.

    Files that end before min_year are skipped without opening them (reading the
    old Excel files is the slow part). Column names are stripped of spaces, and
    each row gets a `source_file` column.
    """
    parts = []
    for path in sorted((raw_dir / dataset).glob("*")):
        if "readme" in path.name or "code" in path.name or path.name in skip_files:
            continue
        latest = _latest_year_in_name(path.name)
        if latest is not None and latest < min_year:
            continue
        if path.suffix == ".csv":
            sheets = {"csv": pd.read_csv(path)}
        else:
            sheets = pd.read_excel(path, sheet_name=None)
        for sheet in sheets.values():
            sheet.columns = [str(c).strip() for c in sheet.columns]
            parts.append(sheet.assign(source_file=path.name))
        logger.info("read %s (%d sheet(s))", path.name, len(sheets))
    if not parts:
        raise FileNotFoundError(
            f"No delay files found in {raw_dir / dataset}. "
            "Run `uv run python -m transitquery.etl.download` first."
        )
    return pd.concat(parts, ignore_index=True)


# --- Logging dropped rows -------------------------------------------------------

class StepLog:
    """Records how many rows each cleaning step removes, so no data disappears silently."""

    def __init__(self, name: str, rows: int):
        self.name = name
        self.rows_in = rows
        self.steps: list[tuple[str, int]] = []
        logger.info("%s: %d raw rows", name, rows)

    def drop(self, df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
        removed = int(mask.sum())
        self.steps.append((reason, removed))
        logger.info("%s: dropped %d rows (%s)", self.name, removed, reason)
        return df.loc[~mask]

    def drop_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.drop(df, df.duplicated(), "exact duplicate")

    def finish(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("%s: %d clean rows (%.1f%% of raw)", self.name, len(df), 100 * len(df) / max(self.rows_in, 1))
        return df.reset_index(drop=True)


# --- Helpers --------------------------------------------------------------------

def rename_and_merge(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    """Rename columns, merging ones that end up with the same name.

    After stacking every sheet, 'Report Date' is filled for 2014-2019 rows and
    'Date' for 2020+ rows; both become one 'date' column holding whichever is set.
    """
    merged = {}
    for raw_name, new_name in columns.items():
        if raw_name not in df:
            continue
        merged[new_name] = merged[new_name].fillna(df[raw_name]) if new_name in merged else df[raw_name]
    return pd.DataFrame(merged, index=df.index)


def map_unique(series: pd.Series, fn: Callable) -> pd.Series:
    """Apply fn once per distinct value (much faster than per row on 100k+ rows)."""
    mapping = {value: fn(value) for value in series.dropna().unique()}
    return series.map(mapping)


def add_time_columns(df: pd.DataFrame, date_col: str = "date", time_col: str = "time") -> pd.DataFrame:
    """Add occurred_at (Toronto time), hour, day_of_week, is_weekend."""
    stamps = [combine_datetime(d, t) for d, t in zip(df[date_col], df[time_col], strict=True)]
    local = pd.to_datetime(pd.Series(stamps, index=df.index, dtype="object"))
    # Clocks go back in November, so 1:00-1:59 happens twice; the raw data can't tell
    # which, so take standard time. Times skipped in March move forward an hour.
    occurred_at = local.dt.tz_localize(TIMEZONE, ambiguous=False, nonexistent="shift_forward")
    return df.assign(
        occurred_at=occurred_at,
        hour=occurred_at.dt.hour.astype("Int64"),
        day_of_week=occurred_at.dt.day_name(),
        is_weekend=occurred_at.dt.dayofweek >= 5,
    )


# --- Bus and streetcar ----------------------------------------------------------

# Every column name seen in the raw bus/streetcar files -> canonical name.
SURFACE_COLUMNS = {
    "Report Date": "date", "Date": "date",
    "Time": "time",
    "Route": "route_raw", "Line": "route_raw",
    "Location": "location_raw", "Station": "location_raw",
    "Incident": "incident",      # plain-English category, up to 2024
    "Code": "code",              # TTC delay code, 2025 on
    "Min Delay": "min_delay", "Delay": "min_delay",
    "Min Gap": "min_gap", "Gap": "min_gap",
    "Direction": "bound", "Bound": "bound",
    "Vehicle": "vehicle",
}

SURFACE_OUTPUT = [
    "occurred_at", "hour", "day_of_week", "is_weekend",
    "route", "location", "incident", "code",
    "min_delay", "min_gap", "bound", "vehicle", "source_file",
]


def clean_surface(raw: pd.DataFrame, name: str, min_year: int = MIN_YEAR) -> pd.DataFrame:
    """Clean raw bus or streetcar rows into the canonical schema."""
    log = StepLog(name, len(raw))
    df = rename_and_merge(raw, {**SURFACE_COLUMNS, "source_file": "source_file"})  # drops Day, _id, Incident ID...
    for col in ("incident", "code"):         # each file has only one of the two
        if col not in df:
            df[col] = None

    df = add_time_columns(df)
    df = log.drop(df, df["occurred_at"].isna(), "date or time unreadable")
    df = log.drop(df, df["occurred_at"].dt.year < min_year, f"before {min_year}")

    df = df.assign(
        route=map_unique(df["route_raw"], normalize_route).astype("Int64"),
        location=map_unique(df["location_raw"], normalize_location),
        incident=map_unique(df["incident"], normalize_incident),
        code=map_unique(df["code"], normalize_incident).str.upper(),
        min_delay=map_unique(df["min_delay"], normalize_delay).astype("Int64"),
        min_gap=map_unique(df["min_gap"], normalize_delay).astype("Int64"),
        bound=map_unique(df["bound"], normalize_bound),
        vehicle=map_unique(df["vehicle"], normalize_vehicle).astype("Int64"),
    )
    df = log.drop(df, df["min_delay"].isna(), "delay missing, negative or over 24h")
    df = log.drop(df, df["route"].isna(), "no usable route")

    df = df[SURFACE_OUTPUT]
    df = log.drop_duplicates(df)
    return log.finish(df)
