"""Unit tests for the cleaning pipeline, on small hand-made frames shaped like the raw files."""

# The raw data has no time zone (all Toronto local time), so tests use naive datetimes.
# ruff: noqa: DTZ001

import datetime as dt

import pandas as pd
import pytest

from transitquery.etl import clean_subway
from transitquery.etl.common import (
    StepLog,
    _latest_year_in_name,
    add_time_columns,
    clean_surface,
    rename_and_merge,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ttc-bus-delay-data-2019.xlsx", 2019),
        ("ttc-subway-delay-jan-2014-april-2017.xlsx", 2017),
        ("ttc-streetcar-delay-data-202009.xlsx", 2020),
        ("ttc-bus-delay-data-since-2025.csv", None),
    ],
)
def test_latest_year_in_name(name, expected):
    assert _latest_year_in_name(name) == expected


def test_rename_and_merge_combines_old_and_new_names():
    raw = pd.DataFrame({
        "Report Date": [dt.datetime(2019, 1, 1), None],
        "Date": [None, dt.datetime(2021, 1, 1)],
        "Day": ["Tuesday", "Friday"],
    })
    df = rename_and_merge(raw, {"Report Date": "date", "Date": "date"})
    assert list(df.columns) == ["date"]                   # Day is dropped
    assert df["date"].tolist() == [dt.datetime(2019, 1, 1), dt.datetime(2021, 1, 1)]


def test_step_log_records_drops():
    df = pd.DataFrame({"x": [1, 2, 3, 3]})
    log = StepLog("test", len(df))
    df = log.drop(df, df["x"] == 1, "is one")
    df = log.drop_duplicates(df)
    df = log.finish(df)
    assert df["x"].tolist() == [2, 3]
    assert log.steps == [("is one", 1), ("exact duplicate", 1)]


def test_add_time_columns():
    df = pd.DataFrame({
        "date": [dt.datetime(2024, 1, 6), "2024-07-01"],
        "time": [dt.time(8, 15), "17:30"],
    })
    out = add_time_columns(df)
    assert out["occurred_at"].tolist() == [
        pd.Timestamp("2024-01-06 08:15", tz="America/Toronto"),
        pd.Timestamp("2024-07-01 17:30", tz="America/Toronto"),
    ]
    assert str(out["occurred_at"].iloc[0].utcoffset()) == "-1 day, 19:00:00"   # EST, -5h
    assert str(out["occurred_at"].iloc[1].utcoffset()) == "-1 day, 20:00:00"   # EDT, -4h
    assert out["hour"].tolist() == [8, 17]
    assert out["day_of_week"].tolist() == ["Saturday", "Monday"]
    assert out["is_weekend"].tolist() == [True, False]


def test_add_time_columns_handles_daylight_saving_edges():
    df = pd.DataFrame({
        "date": ["2024-03-10", "2024-11-03"],
        "time": ["02:30", "01:30"],     # 02:30 doesn't exist; 01:30 happens twice
    })
    out = add_time_columns(df)
    assert out["occurred_at"].notna().all()


def _subway_raw(**overrides):
    row = {
        "Date": dt.datetime(2024, 3, 25), "Time": "12:12", "Day": "Monday",
        "Station": "KENNEDY BD STATION", "Code": "musc", "Min Delay": 5, "Min Gap": 10,
        "Bound": "w", "Line": "BD", "Vehicle": 5011, "source_file": "subway-2024.xlsx",
    }
    return {**row, **overrides}


def test_clean_subway():
    raw = pd.DataFrame([
        _subway_raw(),
        _subway_raw(),                                         # exact duplicate
        _subway_raw(Line="YU/BD", Station="ST GEORGE YUS STATION", Vehicle=0),
        _subway_raw(Line="29 DUFFERIN"),                       # bus route, no usable line
        _subway_raw(**{"Min Delay": -3}),                      # impossible delay
        _subway_raw(Date=dt.datetime(2019, 5, 1)),             # before 2020
    ])
    out = clean_subway.clean(raw, min_year=2020)

    assert list(out.columns) == clean_subway.OUTPUT
    assert len(out) == 2
    first, interchange = out.iloc[0], out.iloc[1]
    assert first["station"] == "KENNEDY"
    assert first["station_raw"] == "KENNEDY BD STATION"
    assert first["line_code"] == "2"
    assert first["line_name"] == "Line 2 Bloor-Danforth"
    assert first["code"] == "MUSC"
    assert first["bound"] == "W"
    assert interchange["line_code"] == "1/2"
    assert interchange["line_name"] == "Line 1 Yonge-University / Line 2 Bloor-Danforth"
    assert interchange["station"] == "ST GEORGE"
    assert pd.isna(interchange["vehicle"])


def test_clean_surface_merges_layouts_and_keeps_incident_and_code_apart():
    raw = pd.DataFrame([
        # 2020 Excel layout: Date/Route/Incident/Min Delay/Direction
        {"Date": dt.datetime(2020, 2, 3), "Route": 52.0, "Time": dt.time(9, 0), "Day": "Monday",
         "Location": "Kennedy Stn", "Incident": "Mechanical", "Min Delay": 10, "Min Gap": 20,
         "Direction": "n/b", "Vehicle": 8393.0, "source_file": "bus-2020.xlsx"},
        # 2019 Excel layout: Report Date/Delay/Gap
        {"Report Date": dt.datetime(2020, 2, 4), "Route": 7, "Time": "10:00", "Day": "Tuesday",
         "Location": "Queen & Leslie", "Incident": "Diversion", "Delay": 15, "Gap": 30,
         "Direction": "B/W", "Vehicle": None, "source_file": "bus-2019.xlsx"},
        # since-2025 CSV layout: Line/Station/Code/Bound
        {"Date": "2025-08-28", "Line": "90 VAUGHAN", "Time": "08:40", "Day": "Thursday",
         "Station": "ST. CLAIR WEST STATION", "Code": "TFCNO", "Min Delay": 7, "Min Gap": 14,
         "Bound": "W", "Vehicle": 0, "source_file": "bus-since-2025.csv"},
        # not a route
        {"Date": "2025-08-28", "Line": "LINE 1 SHUTTLE", "Time": "09:00", "Day": "Thursday",
         "Station": "FINCH STATION", "Code": "MFO", "Min Delay": 7, "Min Gap": 14,
         "Bound": "S", "Vehicle": 0, "source_file": "bus-since-2025.csv"},
    ])
    out = clean_surface(raw, "bus", min_year=2020)

    assert len(out) == 3
    assert out["route"].tolist() == [52, 7, 90]
    assert out["location"].tolist() == ["KENNEDY STATION", "QUEEN AND LESLIE", "ST CLAIR WEST STATION"]
    assert out["min_delay"].tolist() == [10, 15, 7]
    assert out["bound"].tolist() == ["N", "BOTH", "W"]
    assert out["incident"].tolist()[:2] == ["Mechanical", "Diversion"]
    assert pd.isna(out["incident"].iloc[2])
    assert out["code"].iloc[2] == "TFCNO"
    assert out["code"].iloc[:2].isna().all()
    assert out["vehicle"].isna().tolist() == [False, True, True]
