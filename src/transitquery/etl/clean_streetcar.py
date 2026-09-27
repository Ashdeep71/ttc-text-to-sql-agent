"""Clean the streetcar delay files into one table.

Bus and streetcar share a layout, so the work happens in common.clean_surface.
Run on its own:  uv run python -m transitquery.etl.clean_streetcar
"""

import logging

import pandas as pd

from transitquery.etl.common import MIN_YEAR, clean_surface, read_raw

DATASET = "ttc-streetcar-delay-data"

# Byte-for-byte copy of ttc-streetcar-delay-data-2020.xlsx (DATA_NOTES.md #2).
DUPLICATE_FILES = ("ttc-streetcar-delay-data-202009.xlsx",)


def clean(raw: pd.DataFrame, min_year: int = MIN_YEAR) -> pd.DataFrame:
    return clean_surface(raw, "streetcar", min_year)


def main(min_year: int = MIN_YEAR) -> pd.DataFrame:
    return clean(read_raw(DATASET, min_year, skip_files=DUPLICATE_FILES), min_year)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(main().head())
