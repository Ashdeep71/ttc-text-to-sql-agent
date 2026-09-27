"""Clean the subway delay files into one table.

Run on its own:  uv run python -m transitquery.etl.clean_subway
"""

import logging

import pandas as pd

from transitquery.etl.common import (
    MIN_YEAR,
    StepLog,
    add_time_columns,
    map_unique,
    read_raw,
    rename_and_merge,
)
from transitquery.etl.normalize import (
    normalize_bound,
    normalize_delay,
    normalize_incident,
    normalize_line,
    normalize_station,
    normalize_vehicle,
)

DATASET = "ttc-subway-delay-data"

# Subway has kept the same column names since 2014; the since-2025 CSV only adds _id.
COLUMNS = {
    "Date": "date",
    "Time": "time",
    "Station": "station_raw",
    "Code": "code",
    "Min Delay": "min_delay",
    "Min Gap": "min_gap",
    "Bound": "bound",
    "Line": "line_raw",
    "Vehicle": "vehicle",
}

LINE_NAMES = {
    "1": "Line 1 Yonge-University",
    "2": "Line 2 Bloor-Danforth",
    "3": "Line 3 Scarborough",
    "4": "Line 4 Sheppard",
}

OUTPUT = [
    "occurred_at", "hour", "day_of_week", "is_weekend",
    "line_code", "line_name", "station", "station_raw", "code",
    "min_delay", "min_gap", "bound", "vehicle", "source_file",
]


def line_name(line_code: str | None) -> str | None:
    """'1' -> 'Line 1 Yonge-University'; '1/2' -> 'Line 1 Yonge-University / Line 2 Bloor-Danforth'."""
    if line_code is None:
        return None
    return " / ".join(LINE_NAMES[number] for number in line_code.split("/"))


def clean(raw: pd.DataFrame, min_year: int = MIN_YEAR) -> pd.DataFrame:
    log = StepLog("subway", len(raw))
    df = rename_and_merge(raw, {**COLUMNS, "source_file": "source_file"})

    df = add_time_columns(df)
    df = log.drop(df, df["occurred_at"].isna(), "date or time unreadable")
    df = log.drop(df, df["occurred_at"].dt.year < min_year, f"before {min_year}")

    line_code = map_unique(df["line_raw"], normalize_line)
    df = df.assign(
        line_code=line_code,
        line_name=map_unique(line_code, line_name),
        station=map_unique(df["station_raw"], normalize_station),
        station_raw=df["station_raw"].str.strip(),
        code=map_unique(df["code"], normalize_incident).str.upper(),
        min_delay=map_unique(df["min_delay"], normalize_delay).astype("Int64"),
        min_gap=map_unique(df["min_gap"], normalize_delay).astype("Int64"),
        bound=map_unique(df["bound"], normalize_bound),
        vehicle=map_unique(df["vehicle"], normalize_vehicle).astype("Int64"),
    )
    df = log.drop(df, df["min_delay"].isna(), "delay missing, negative or over 24h")
    df = log.drop(df, df["line_code"].isna(), "no usable line")

    df = df[OUTPUT]
    df = log.drop_duplicates(df)
    return log.finish(df.sort_values("occurred_at", kind="stable"))


def main(min_year: int = MIN_YEAR) -> pd.DataFrame:
    return clean(read_raw(DATASET, min_year), min_year)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(main().head())
