"""Unit tests for transitquery.etl.normalize.

The inputs are real values seen in the raw TTC files (see DATA_NOTES.md).
"""

# The raw data has no time zone (all Toronto local time), so tests use naive datetimes.
# ruff: noqa: DTZ001

import datetime as dt
import math

import pandas as pd
import pytest

from transitquery.etl.normalize import (
    SUBWAY_STATIONS,
    combine_datetime,
    normalize_bound,
    normalize_delay,
    normalize_incident,
    normalize_line,
    normalize_location,
    normalize_route,
    normalize_station,
    normalize_vehicle,
)

# Every normalizer should treat these as "no value".
BLANKS = [None, float("nan"), pd.NA, pd.NaT, "", "   "]

ALL_NORMALIZERS = [
    normalize_bound,
    normalize_delay,
    normalize_incident,
    normalize_line,
    normalize_location,
    normalize_route,
    normalize_station,
    normalize_vehicle,
]


@pytest.mark.parametrize("fn", ALL_NORMALIZERS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("blank", BLANKS, ids=repr)
def test_blank_input_returns_none(fn, blank):
    assert fn(blank) is None


# --- normalize_bound --------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("N", "N"),
        ("n", "N"),
        (" S ", "S"),
        ("NB", "N"),
        ("nb", "N"),
        ("N/B", "N"),
        ("w/b", "W"),
        ("EB", "E"),
        ("eastbound", "E"),
        ("Southbound", "S"),
        ("B/W", "BOTH"),
        ("bw", "BOTH"),
        ("B/W's", "BOTH"),
        ("Bothways", "BOTH"),
    ],
)
def test_normalize_bound(raw, expected):
    assert normalize_bound(raw) == expected


@pytest.mark.parametrize("raw", ["B", "Y", "R", "0", "5", "up", "down", "N/S", "E/W", "EW", "Service adjusted."])
def test_normalize_bound_ambiguous_or_junk(raw):
    assert normalize_bound(raw) is None


# --- normalize_line ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("YU", "1"),
        ("YUS", "1"),
        ("LINE 1", "1"),
        ("YU LINE", "1"),
        ("BD", "2"),
        ("B/D", "2"),
        ("BD LINE", "2"),
        ("BLOOR DANFORTH", "2"),
        ("LINE 2 - BLOOR DANFORT", "2"),   # cut off at 22 characters
        ("LINE 2 SHUTTLE", "2"),
        ("SRT", "3"),
        ("RT", "3"),
        ("SHP", "4"),
        ("SHEP", "4"),
        ("SHEPPARD", "4"),
    ],
)
def test_normalize_line_single(raw, expected):
    assert normalize_line(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("YU/BD", "1/2"),
        ("YU / BD", "1/2"),
        ("YU/ BD", "1/2"),
        ("BD/YU", "1/2"),      # order in the raw value doesn't matter
        ("YU & BD", "1/2"),
        ("YU - BD", "1/2"),
        ("YU\\BD", "1/2"),
        ("YUS/DB", "1/2"),     # typo for BD
        ("YUS/BD/SHP", "1/2/4"),
        ("YU/SHEP", "1/4"),
    ],
)
def test_normalize_line_interchange(raw, expected):
    assert normalize_line(raw) == expected


@pytest.mark.parametrize("raw", ["999", "29 DUFFERIN", "504 KING", "52", "EC", "TRANSIT CONTROL", "WOODBINE STN"])
def test_normalize_line_rejects_routes_and_junk(raw):
    assert normalize_line(raw) is None


# --- normalize_route --------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (52, 52),
        (52.0, 52),
        ("52", 52),
        ("52 LAWRENCE WEST", 52),
        ("960 STEELES WEST EXPRE", 960),
        ("504A KING", 504),
        ("504B KING", 504),
        ("301 QUEEN NIGHT", 301),
    ],
)
def test_normalize_route(raw, expected):
    result = normalize_route(raw)
    assert result == expected
    assert isinstance(result, int)


@pytest.mark.parametrize("raw", ["RAD", "OTC", "TEST CAR", "BD", "YU", "LINE 1 SHUTTLE", "RAD 600", 0])
def test_normalize_route_rejects_non_routes(raw):
    assert normalize_route(raw) is None


# --- normalize_station ------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # plain names and casing
        ("FINCH STATION", "FINCH"),
        ("finch station", "FINCH"),
        ("MAIN STREET STATION", "MAIN STREET"),
        ("QUEEN'S PARK STATION", "QUEEN'S PARK"),
        ("ST. GEORGE STATION", "ST GEORGE"),
        # line tags on interchange stations
        ("KENNEDY BD STATION", "KENNEDY"),
        ("KENNEDY SRT STATION", "KENNEDY"),
        ("ST GEORGE YUS STATION", "ST GEORGE"),
        ("ST GEORGE BD STATION", "ST GEORGE"),
        ("SPADINA YU STATION", "SPADINA"),
        # names cut off at 22 characters
        ("PIONEER VILLAGE STATIO", "PIONEER VILLAGE"),
        ("YORK UNIVERSITY STATIO", "YORK UNIVERSITY"),
        ("NORTH YORK CENTRE STAT", "NORTH YORK CENTRE"),
        # aliases and abbreviations
        ("BLOOR STATION", "BLOOR-YONGE"),
        ("YONGE BD STATION", "BLOOR-YONGE"),
        ("YONGE AND BLOOR", "BLOOR-YONGE"),
        ("YONGE SHP STATION", "SHEPPARD-YONGE"),
        ("SHEPPARD STATION", "SHEPPARD-YONGE"),
        ("VMC STATION", "VAUGHAN METROPOLITAN CENTRE"),
        ("VAUGHAN MC STATION", "VAUGHAN METROPOLITAN CENTRE"),
        ("NORTH YORK CTR STATION", "NORTH YORK CENTRE"),
        ("SCARB CTR STATION", "SCARBOROUGH CENTRE"),
        # renamed stations use the current name
        ("DOWNSVIEW STATION", "SHEPPARD WEST"),
        ("EGLINTON WEST STATION", "CEDARVALE"),
        ("CEDARVALE YU STATION", "CEDARVALE"),
        ("DUNDAS STATION", "TMU"),
        ("TMU STATION", "TMU"),
        ("DUNDAS WEST STATION", "DUNDAS WEST"),   # must not become TMU
        # typos and notes after the name
        ("BLOOR STATON", "BLOOR-YONGE"),
        ("Kennedy Stn", "KENNEDY"),
        ("WILSON STATION (EXITIN", "WILSON"),
        ("DUPONT STATION ( APPRO", "DUPONT"),
        ("KENNEDY BD STATION - P", "KENNEDY"),
        ("KIPLING STATION PLATFO", "KIPLING"),
        ("VMC STATION PLATFORM 2", "VAUGHAN METROPOLITAN CENTRE"),
        ("EGLINTON STATION (MIGR", "EGLINTON"),
    ],
)
def test_normalize_station(raw, expected):
    assert normalize_station(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        # whole lines
        "YONGE UNIVERSITY LINE",
        "BLOOR DANFORTH SUBWAY",
        "YUS/BD/SHEPPARD SUBWAY",
        # between two stations
        "UNION STATION TO KING",
        "KENNEDY SRT STATION TO",
        "WELLESLEY TO COLLEGE",
        # yards and buildings
        "GREENWOOD YARD",
        "WILSON CAPITAL SHOP",
        "MCBRIEN BUILDING",
    ],
)
def test_normalize_station_rejects_non_stations(raw):
    assert normalize_station(raw) is None


def test_every_station_maps_to_itself():
    for name in SUBWAY_STATIONS:
        assert normalize_station(f"{name} STATION") == name


# --- normalize_location -----------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kennedy Station", "KENNEDY STATION"),
        ("kennedy station", "KENNEDY STATION"),
        ("Kennedy Stn", "KENNEDY STATION"),
        ("Kennedy Stn.", "KENNEDY STATION"),
        ("Queen & Leslie", "QUEEN AND LESLIE"),
        ("Queen&Leslie", "QUEEN AND LESLIE"),
        ("  QUEEN   AND  LESLIE ", "QUEEN AND LESLIE"),
        ("Entire Route.", "ENTIRE ROUTE"),
        ("St. Clair West Station", "ST CLAIR WEST STATION"),
    ],
)
def test_normalize_location(raw, expected):
    assert normalize_location(raw) == expected


# --- normalize_incident -----------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Mechanical", "Mechanical"),
        ("Late ", "Late"),
        ("  Cleaning -  Unsanitary ", "Cleaning - Unsanitary"),
        ("MUSC", "MUSC"),
        ("e", None),
    ],
)
def test_normalize_incident(raw, expected):
    assert normalize_incident(raw) == expected


# --- normalize_delay / normalize_vehicle ------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (5, 5), (5.0, 5), ("12", 12), (1440, 1440), (-54, None), (1441, None), (246245, None), ("abc", None)],
)
def test_normalize_delay(raw, expected):
    assert normalize_delay(raw) == expected


def test_normalize_delay_custom_cap():
    assert normalize_delay(90, max_minutes=60) is None
    assert normalize_delay(60, max_minutes=60) == 60


@pytest.mark.parametrize(("raw", "expected"), [(5227, 5227), (5227.0, 5227), (0, None), ("x", None)])
def test_normalize_vehicle(raw, expected):
    assert normalize_vehicle(raw) == expected


# --- combine_datetime -------------------------------------------------------------

@pytest.mark.parametrize(
    ("date", "time"),
    [
        (dt.datetime(2019, 1, 1), dt.time(8, 15)),             # Excel: datetime + time object
        (pd.Timestamp("2019-01-01"), dt.time(8, 15)),
        ("2019-01-01", "08:15"),                                # CSV: two strings
        ("2019-01-01", "8:15"),
        (dt.datetime(2019, 1, 1), "08:15"),                     # mixed
        (dt.datetime(2019, 1, 1), dt.datetime(1940, 1, 1, 8, 15)),  # Excel cell stored as a full datetime
        (dt.datetime(2019, 1, 1, 23, 0), dt.time(8, 15)),       # time part of the date is ignored
    ],
)
def test_combine_datetime(date, time):
    assert combine_datetime(date, time) == pd.Timestamp(2019, 1, 1, 8, 15)


def test_combine_datetime_keeps_seconds():
    assert combine_datetime("2025-03-02", "23:59:30") == pd.Timestamp(2025, 3, 2, 23, 59, 30)


@pytest.mark.parametrize(
    ("date", "time"),
    [
        (None, "08:15"),
        (float("nan"), "08:15"),
        ("not a date", "08:15"),
        ("2019-01-01", None),
        ("2019-01-01", float("nan")),
        ("2019-01-01", "25:00"),
        ("2019-01-01", "08:75"),
        ("2019-01-01", "8.15"),
        ("2019-01-01", "morning"),
    ],
)
def test_combine_datetime_invalid(date, time):
    assert combine_datetime(date, time) is None


def test_combine_datetime_returns_timestamp():
    result = combine_datetime("2019-01-01", "08:15")
    assert isinstance(result, pd.Timestamp)
    assert not math.isnan(result.value)
