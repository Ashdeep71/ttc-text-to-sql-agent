"""Run the whole ETL: download -> clean -> write data/processed/.

    uv run python -m transitquery.etl.run                   # everything
    uv run python -m transitquery.etl.run --skip-download   # reuse data/raw as is
    uv run python -m transitquery.etl.run --min-year 2020   # keep less history

Writes one gzipped CSV per database table, plus a README with row counts,
what each cleaning step dropped, and where the data came from.
"""

import argparse
import datetime as dt
import logging

import pandas as pd

from transitquery.etl import (
    clean_bus,
    clean_codes,
    clean_streetcar,
    clean_subway,
    download,
)
from transitquery.etl.common import MIN_YEAR, PROJECT_ROOT

logger = logging.getLogger(__name__)

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
SOURCE_PAGE = "https://open.toronto.ca/dataset/{}/"

# output table name -> cleaner module
TABLES = {
    "subway_delays": clean_subway,
    "bus_delays": clean_bus,
    "streetcar_delays": clean_streetcar,
}


def write_table(df: pd.DataFrame, name: str) -> None:
    path = PROCESSED_DIR / f"{name}.csv.gz"
    df.to_csv(path, index=False)
    logger.info("wrote %s (%d rows, %.1f MB)", path.name, len(df), path.stat().st_size / 1e6)


def build_readme(tables: dict[str, pd.DataFrame], min_year: int) -> str:
    lines = [
        "# Processed TTC delay data",
        "",
        f"Generated {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC by `uv run python -m transitquery.etl.run`.",
        "Do not edit by hand.",
        f"Years kept: {min_year} onward. Timestamps (`occurred_at`) are America/Toronto.",
        "",
        "## Tables",
        "",
        "| File | Rows | From | To |",
        "|---|---|---|---|",
    ]
    for name, df in tables.items():
        if "occurred_at" in df:
            first, last = f"{df['occurred_at'].min():%Y-%m-%d}", f"{df['occurred_at'].max():%Y-%m-%d}"
        else:
            first = last = ""
        lines.append(f"| `{name}.csv.gz` | {len(df):,} | {first} | {last} |")

    lines += ["", "## Rows removed during cleaning", ""]
    for name, df in tables.items():
        rows_in = df.attrs.get("rows_in", len(df))
        lines.append(f"**{name}**: {rows_in:,} raw rows → {len(df):,} kept ({100 * len(df) / max(rows_in, 1):.1f}%)")
        lines += [f"- {reason}: {count:,}" for reason, count in df.attrs.get("steps", [])]
        lines.append("")

    lines += ["## Columns", ""]
    for name, df in tables.items():
        lines.append(f"- **{name}**: {', '.join(f'`{c}`' for c in df.columns)}")

    lines += [
        "",
        "## Sources",
        "",
        "City of Toronto Open Data, published by the TTC:",
        "",
        *[f"- {SOURCE_PAGE.format(module.DATASET)}" for module in TABLES.values()],
        "",
        "Known data problems and how each is handled: see `DATA_NOTES.md` in the project root.",
        "",
    ]
    return "\n".join(lines)


def run(min_year: int = MIN_YEAR, skip_download: bool = False) -> dict[str, pd.DataFrame]:
    if skip_download:
        logger.info("skipping download, using existing data/raw")
    else:
        download.download_all()

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    tables = {}
    for name, module in TABLES.items():
        tables[name] = module.main(min_year)
        write_table(tables[name], name)
    tables["delay_codes"] = clean_codes.clean()
    write_table(tables["delay_codes"], "delay_codes")

    (PROCESSED_DIR / "README.md").write_text(build_readme(tables, min_year), encoding="utf-8")
    logger.info("wrote README.md")
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description="Download, clean and write the TTC delay data.")
    parser.add_argument("--skip-download", action="store_true", help="use the files already in data/raw")
    parser.add_argument("--min-year", type=int, default=MIN_YEAR, help=f"first year to keep (default {MIN_YEAR})")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(min_year=args.min_year, skip_download=args.skip_download)


if __name__ == "__main__":
    main()
