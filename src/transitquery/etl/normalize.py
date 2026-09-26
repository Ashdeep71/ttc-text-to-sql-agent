"""Pure functions that turn messy raw TTC values into one standard form.

Each function takes a single raw value and returns the clean value, or None
when the input is blank or junk. No files, no database, so they're easy to
unit-test. The numbers in comments (#5, #14...) refer to items in DATA_NOTES.md.
"""

import datetime as dt
import math
import re

import pandas as pd


def _is_blank(value) -> bool:
    """True for None, NaN, NaT and empty/whitespace strings."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    return isinstance(value, str) and not value.strip()


def _clean_text(value) -> str:
    """Uppercase, trim, and collapse repeated spaces."""
    return re.sub(r"\s+", " ", str(value).strip().upper())


# --- Direction (#14) ---------------------------------------------------------

_BOTH_WAYS = {"B/W", "BW", "B/WS", "BWS", "BOTH", "BOTHWAYS", "BOTH WAYS", "BOTH WAY"}
_DIRECTION = re.compile(r"^([NSEW])(?:ORTH|OUTH|AST|EST)?\s*(?:/?\s*B(?:OUND)?)?$")


def normalize_bound(value) -> str | None:
    """'n/b', 'NB', 'Northbound', 'N' -> 'N'; 'B/W' -> 'BOTH'.

    Ambiguous values ('B', 'up', 'down', 'N/S', 'E/W') and junk -> None.
    """
    if _is_blank(value):
        return None
    text = _clean_text(value).replace("'", "")
    if text in _BOTH_WAYS:
        return "BOTH"
    match = _DIRECTION.match(text)
    return match.group(1) if match else None


# --- Subway line (#5) ----------------------------------------------------------

# Checked in order against the whole string; every match adds that line.
_LINE_PATTERNS = [
    ("1", re.compile(r"\bYUS?\b|\bY/U\b|YONGE|UNIVERSITY|LINE\s*1\b")),
    ("2", re.compile(r"\bBD\b|\bB/D\b|\bDB\b|BLOOR|DANFORTH|LINE\s*2\b")),
    ("3", re.compile(r"\bSRT\b|\bRT\b|SCARBOROUGH|LINE\s*3\b")),
    ("4", re.compile(r"\bSHP\b|\bSHEP|SHEPPARD|LINE\s*4\b")),
]


def normalize_line(value) -> str | None:
    """Map a subway line to its number: 'YUS' -> '1', 'B/D' -> '2'.

    Incidents at interchanges list several lines: 'YU/BD' -> '1/2'.
    Bus routes that ended up in this column ('29 DUFFERIN') and junk ('999') -> None.
    """
    if _is_blank(value):
        return None
    text = _clean_text(value)
    if re.match(r"^\d", text):          # starts with a number: a bus route or junk
        return None
    lines = [number for number, pattern in _LINE_PATTERNS if pattern.search(text)]
    return "/".join(lines) if lines else None


# --- Bus / streetcar route (#6, #7) --------------------------------------------

def normalize_route(value) -> int | None:
    """52, 52.0, '52', '52 LAWRENCE WEST', '504A KING' -> the route number.

    Values that aren't routes ('RAD', 'OTC', 'TEST CAR', 'BD') -> None.
    """
    if _is_blank(value):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
    else:
        match = re.match(r"^\s*(\d+)", str(value))
        if not match:
            return None
        number = int(match.group(1))
    return number if number > 0 else None


# --- Subway station (#8-#12) ---------------------------------------------------

# Current official names. Old names and abbreviations are mapped in _STATION_ALIASES.
SUBWAY_STATIONS = frozenset({
    # Line 1 Yonge-University
    "FINCH", "NORTH YORK CENTRE", "SHEPPARD-YONGE", "YORK MILLS", "LAWRENCE", "EGLINTON",
    "DAVISVILLE", "ST CLAIR", "SUMMERHILL", "ROSEDALE", "BLOOR-YONGE", "WELLESLEY",
    "COLLEGE", "TMU", "QUEEN", "KING", "UNION", "ST ANDREW", "OSGOODE", "ST PATRICK",
    "QUEEN'S PARK", "MUSEUM", "ST GEORGE", "SPADINA", "DUPONT", "ST CLAIR WEST",
    "CEDARVALE", "GLENCAIRN", "LAWRENCE WEST", "YORKDALE", "WILSON", "SHEPPARD WEST",
    "DOWNSVIEW PARK", "FINCH WEST", "YORK UNIVERSITY", "PIONEER VILLAGE", "HIGHWAY 407",
    "VAUGHAN METROPOLITAN CENTRE",
    # Line 2 Bloor-Danforth (ST GEORGE, SPADINA, BLOOR-YONGE are listed above)
    "KIPLING", "ISLINGTON", "ROYAL YORK", "OLD MILL", "JANE", "RUNNYMEDE", "HIGH PARK",
    "KEELE", "DUNDAS WEST", "LANSDOWNE", "DUFFERIN", "OSSINGTON", "CHRISTIE", "BATHURST",
    "BAY", "SHERBOURNE", "CASTLE FRANK", "BROADVIEW", "CHESTER", "PAPE", "DONLANDS",
    "GREENWOOD", "COXWELL", "WOODBINE", "MAIN STREET", "VICTORIA PARK", "WARDEN", "KENNEDY",
    # Line 3 Scarborough RT (closed 2023; KENNEDY is listed above)
    "LAWRENCE EAST", "ELLESMERE", "MIDLAND", "SCARBOROUGH CENTRE", "MCCOWAN",
    # Line 4 Sheppard (SHEPPARD-YONGE is listed above)
    "BAYVIEW", "BESSARION", "LESLIE", "DON MILLS",
})

# Looked up after the "STATION" suffix is removed, before line tags are removed,
# because 'YONGE BD' and 'YONGE SHP' are different stations.
_STATION_ALIASES = {
    "BLOOR": "BLOOR-YONGE",
    "YONGE": "BLOOR-YONGE",
    "YONGE BD": "BLOOR-YONGE",
    "YONGE AND BLOOR": "BLOOR-YONGE",
    "BLOOR YONGE": "BLOOR-YONGE",
    "YONGE SHP": "SHEPPARD-YONGE",
    "YONGE SHEP": "SHEPPARD-YONGE",
    "SHEPPARD": "SHEPPARD-YONGE",           # name before 2002
    "SHEPPARD YONGE": "SHEPPARD-YONGE",
    "DOWNSVIEW": "SHEPPARD WEST",           # renamed 2017
    "EGLINTON WEST": "CEDARVALE",           # renamed 2024
    "DUNDAS": "TMU",                        # renamed 2024
    "VMC": "VAUGHAN METROPOLITAN CENTRE",
    "VAUGHAN MC": "VAUGHAN METROPOLITAN CENTRE",
    "NORTH YORK CTR": "NORTH YORK CENTRE",
    "SCARB CTR": "SCARBOROUGH CENTRE",
    "SCARBOROUGH CTR": "SCARBOROUGH CENTRE",
}

# "STATION" and its truncated/misspelt forms, plus anything after it
# ('KIPLING STATION PLATFORM 2', 'PIONEER VILLAGE STATIO').
_STATION_SUFFIX = re.compile(r"\s+(?:STATIONS?|STATIO|STATI|STAT|STA|STN|STATON)\b.*$")
_LINE_TAG = re.compile(r"\s+(?:YUS|YU|BD|SRT|SHP)$")


def normalize_station(value) -> str | None:
    """Map a raw subway location to one of SUBWAY_STATIONS.

    'KENNEDY BD STATION', 'Kennedy Stn', 'KENNEDY SRT STATION' -> 'KENNEDY'
    'PIONEER VILLAGE STATIO' (cut off at 22 chars) -> 'PIONEER VILLAGE'
    Segments ('UNION TO KING'), whole lines, yards and buildings -> None.
    """
    if _is_blank(value):
        return None
    text = _clean_text(value).replace(".", "")
    if " TO " in text or text.endswith(" TO"):
        return None                                         # between two stations
    text = re.sub(r"\s*\(.*$", "", text)                    # '(APPROACHING...'
    text = re.sub(r"\s+-\s.*$|\s+-$", "", text)             # ' - PLATFORM 1'
    text = _STATION_SUFFIX.sub("", text)
    text = re.sub(r"\s+PLATFORM.*$", "", text)

    if text in _STATION_ALIASES:
        return _STATION_ALIASES[text]
    text = _LINE_TAG.sub("", text)                          # 'ST GEORGE YUS' -> 'ST GEORGE'
    text = _STATION_ALIASES.get(text, text)
    return text if text in SUBWAY_STATIONS else None


# --- Bus / streetcar location (#13) ------------------------------------------

def normalize_location(value) -> str | None:
    """Light cleanup of free-text locations: 'Kennedy Stn' -> 'KENNEDY STATION',
    'Queen & Leslie' -> 'QUEEN AND LESLIE'. Doesn't try to map every value."""
    if _is_blank(value):
        return None
    text = _clean_text(value)
    text = re.sub(r"\s*&\s*", " AND ", text)
    text = re.sub(r"\bSTN\b\.?", "STATION", text)
    text = text.rstrip(".,;: ")
    return text or None


# --- Reason text (#17) ----------------------------------------------------------

def normalize_incident(value) -> str | None:
    """'Late ' -> 'Late'; one-letter junk like 'e' -> None. Keeps original casing."""
    if _is_blank(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text if len(text) > 1 else None


# --- Numbers (#20, #21) --------------------------------------------------------

MAX_DELAY_MINUTES = 24 * 60


def normalize_delay(value, max_minutes: int = MAX_DELAY_MINUTES) -> int | None:
    """Minutes of delay or gap. Negative or longer than max_minutes -> None."""
    if _is_blank(value):
        return None
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return None
    return minutes if 0 <= minutes <= max_minutes else None


def normalize_vehicle(value) -> int | None:
    """Vehicle number; 0 means 'none recorded' -> None."""
    if _is_blank(value):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# --- Date and time (#4, #18) -------------------------------------------------

_TIME_TEXT = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def _parse_time(value) -> dt.time | None:
    if _is_blank(value):
        return None
    if isinstance(value, dt.datetime):          # also covers pd.Timestamp
        return value.time()
    if isinstance(value, dt.time):
        return value
    match = _TIME_TEXT.match(str(value).strip())
    if not match:
        return None
    hour, minute, second = (int(g) if g else 0 for g in match.groups())
    if hour > 23 or minute > 59 or second > 59:
        return None
    return dt.time(hour, minute, second)


def combine_datetime(date, time) -> pd.Timestamp | None:
    """Join a date and a time of day into one timestamp.

    date: datetime, pd.Timestamp or 'YYYY-MM-DD' string.
    time: datetime.time (Excel), 'HH:MM' string (CSV), or a full datetime
          (a few Excel cells), whose time part is used.
    Returns None if either part can't be parsed.
    """
    if _is_blank(date):
        return None
    try:
        day = pd.Timestamp(date).normalize()
    except (TypeError, ValueError):
        return None
    if day is pd.NaT:
        return None
    clock = _parse_time(time)
    if clock is None:
        return None
    return day.replace(hour=clock.hour, minute=clock.minute, second=clock.second)
