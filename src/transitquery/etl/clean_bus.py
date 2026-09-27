"""Clean the bus delay files into one table.

Bus and streetcar share a layout, so the work happens in common.clean_surface.
Run on its own:  uv run python -m transitquery.etl.clean_bus
"""

import logging

import pandas as pd

from transitquery.etl.common import MIN_YEAR, clean_surface, read_raw

DATASET = "ttc-bus-delay-data"


def clean(raw: pd.DataFrame, min_year: int = MIN_YEAR) -> pd.DataFrame:
    return clean_surface(raw, "bus", min_year)


def main(min_year: int = MIN_YEAR) -> pd.DataFrame:
    return clean(read_raw(DATASET, min_year), min_year)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(main().head())
