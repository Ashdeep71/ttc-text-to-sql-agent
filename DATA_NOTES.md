# TTC delay data: known issues

Findings from exploring the raw files in `notebooks/01-cleaner.ipynb`
(data downloaded 2026-09-25, covering Jan 2014 – Aug 2026).
Each issue lists what we'll do about it and where that happens.

## Overview

| | Subway | Bus | Streetcar |
|---|---|---|---|
| Raw rows | 267,842 | 809,655 | 178,758 |
| Files | 10 | 12 | 13 (one is a duplicate) |
| Distinct column layouts | 2 | 8 | 5 |
| Distinct location strings | 2,223 | 137,446 | 24,969 |
| Reason column | TTC code, all years | text category → TTC code in 2025 | text category → TTC code in 2025 |

## Files and structure

1. **Monthly sheets.** Files up to 2021 split the year into one sheet per month; 2022+ use a single sheet.
   Sheet names are inconsistent (`Jan18`, `Jan 19`, `January21`, `March '20`, `June 2019 ` with a trailing space).
   → Read with `sheet_name=None` and concatenate; never rely on sheet names. *(clean_\*.py)*
2. **Duplicate file.** `ttc-streetcar-delay-data-2020.xlsx` and `ttc-streetcar-delay-data-202009.xlsx` are byte-for-byte identical (7,830 rows).
   → Skip `202009`. *(clean_streetcar.py)*
3. **Since-2025 CSVs** have an extra `_id` column (just a row number).
   → Drop it. *(clean_\*.py)*
4. **Data types differ by format.** `Date` is a datetime in Excel files and a `"YYYY-MM-DD"` string in the CSVs.
   → Parse everything with `pd.to_datetime`. *(normalize.combine_datetime)*

## Column names (bus and streetcar)

The same field appears under different names depending on the year:

| Canonical | Names in the raw files |
|---|---|
| `date` | `Report Date` (2014–2019), `Date` (2020+) |
| `route` | `Route`, `Line` (bus Jul–Aug 2021 and CSV; streetcar Aug 2020+) |
| `location` | `Location`, `Station` (CSV) |
| `incident` / `code` | `Incident` (text), `Code` (CSV) |
| `min_delay` | `Min Delay`, `' Min Delay'` (leading space, bus Mar 2018), `Delay` (2019–2020) |
| `min_gap` | `Min Gap`, `Gap` |
| `bound` | `Direction`, `Bound` |

Stray columns: `Incident ID` (Apr 2019 only), `Unnamed: 10` (bus Dec 2021, one value).
→ One rename map per mode; strip whitespace from column names first; drop anything not in the canonical schema. *(clean_\*.py)*

## Line / route

5. **Subway `Line` has 111 spellings for 4 lines.**
   `YU`, `YUS`, `LINE 1`, `YU LINE` → Line 1; `BD`, `B/D`, `BD LINE`, `BLOOR DANFORTH`, `LINE 2 …` → Line 2; `SHP`, `SHEP`, `SHEPPARD` → Line 4; `SRT`, `RT` → Line 3.
   Combined values (`YU/BD`, `YU / BD`, `BD/YU`, `YU & BD`, `YUS/BD/SHP`…) mean the incident was at an interchange.
   Also bus routes (`29 DUFFERIN`, `504 KING`), junk (`999`, `TRANSIT CONTROL`, `EC`) and 876 blanks.
   → `normalize_line()`: map known spellings, keep combined values as a separate `multi_line` flag, set the rest to null. *(normalize.py)*
6. **Bus/streetcar route type changes.** Integer through 2019 (`52`), sometimes float from 2020 (`52.0`), text with the name in the CSV (`52 LAWRENCE WEST`, cut at 22 characters).
   → `normalize_route()`: extract the leading number, keep the name separately if present. *(normalize.py)*
7. **Streetcar route oddities:** branch letters (`504A`, `504B`), night routes (`301 QUEEN NIGHT`), non-routes (`RAD`, `OTC`, `TEST CAR`), subway lines (`BD`, `YU`).
   → Branch letters collapse to the base route; non-routes become null. *(normalize.py)*

## Location / station

8. **Subway station names are cut off at 22 characters** (`PIONEER VILLAGE STATIO`, `YONGE-UNIVERSITY AND B`).
9. **Interchange stations are split by line:** `ST GEORGE YUS STATION` / `ST GEORGE BD STATION`, `KENNEDY BD` / `KENNEDY SRT`, `YONGE BD` / `YONGE SHP` / `BLOOR STATION`.
10. **Aliases:** `VMC STATION` vs `VAUGHAN MC STATION`, `SHEPPARD-YONGE` vs `YONGE SHP`, `NORTH YORK CTR` (abbreviated).
11. **Not a station:** whole lines (`YONGE UNIVERSITY LINE`, `BLOOR DANFORTH SUBWAY`), segments (`WELLESLEY TO COLLEGE`), buildings and yards (`WILSON CAPITAL SHOP`, `MC BRIEN BUILDING`).
12. **Typos and notes:** `BLOOR STATON`, `DOWNSVIEWSTATION`, `WILSON STATION (EXITIN`, `DUPONT STATION ( APPRO`.
    → `normalize_station()`: uppercase, trim, strip `(…)` notes, fix `STN`/`STATON`, then map to a canonical list of ~75 stations
    (fuzzy prefix match handles truncation). Anything unmatched becomes null and keeps the raw text in `location_raw`. *(normalize.py)*
13. **Bus/streetcar locations are free text** (137k and 25k distinct values). Casing alone gives 7 versions of `KENNEDY STATION`;
    intersections appear in both orders (`QUEEN AND RONCESVALLES` / `Roncesvalles and Queen`); `STC`, `Entire Route`, `Kennedy Stn`.
    → Light cleanup only: uppercase, trim, collapse spaces, `STN` → `STATION`, `&` → `AND`. Don't try to map every value. *(normalize.py)*

## Direction

14. **Bound should be N/S/E/W**, but bus uses ~40 forms (`N`, `n`, `NB`, `N/B`, `n/b`, `nb`…), `B/W`, `BW` (both ways), `eastbound`, `EW`, digits, and single letters `B`, `Y`, `R`, `M`, `D`.
    → `normalize_bound()`: first letter of N/S/E/W forms; `B/W` → `BOTH`; everything else null. *(normalize.py)*

## Reason for the delay

15. **Subway uses TTC codes** (`MUSC`, `SUDP`…). 3.7% of rows use a code missing from `code-descriptions.csv`.
    → Keep the code; join descriptions where available; unknown codes stay as-is. *(clean_subway.py)*
16. **Bus/streetcar changed systems in 2025.** Up to 2024 the column is a plain-English category (`Mechanical`, `Diversion`); from 2025 it's a TTC code (`EFO`, `MTDV`).
    These don't map one-to-one.
    → Two columns: `incident_category` (≤2024) and `code` (2025+). Don't pretend they're the same thing. *(clean_bus.py, clean_streetcar.py)*
17. Incident text has near-duplicates (`Late` vs `Late ` with a trailing space) and junk (`e`).
    → Strip whitespace; junk → null.

## Time

18. **`Time` is mixed:** Python `time` objects (Excel), `"HH:MM"` strings (CSV and some Excel sheets), and a few full datetimes (33 bus, 8 streetcar), including `1940-10-01`.
    → `combine_datetime(date, time)` accepts all three and returns one timestamp; unparseable times → null. *(normalize.py)*

## Delay values

19. **Zero delays.** 65% of subway rows have `Min Delay = 0` (an incident was logged but caused no delay). Only ~4–7% for bus/streetcar.
    → Keep them; they're real incidents. Queries about "delays" should filter `min_delay > 0`. Document this for the agent.
20. **Impossible values.** Bus has 10 negative delays and a maximum of 246,245 minutes (~171 days); 2,744 bus rows exceed 10 hours. Subway maxes at 999, which looks like a placeholder.
    → Drop negatives; set values above a cap (e.g. 24 h) to null and log how many. *(clean_\*.py)*
21. **`Vehicle = 0`** means no vehicle recorded (33% of subway rows). Bus/streetcar use blanks instead.
    → Treat `0` as null.

## Duplicates

22. **Exact duplicate rows:** 269 subway, 1,788 bus, 8,093 streetcar (7,830 of those from the duplicate 2020 file).
    → Skip the duplicate file, then drop remaining exact duplicates and log the count. *(clean_\*.py)*

## Missing values

23. Blanks worth knowing about: subway `Bound` 74k, `Line` 876; bus `Bound` 70k, `Vehicle` 70k, `Route` 3.1k; streetcar `Bound` 17k, `Vehicle` 4.7k.
    → Keep rows with a missing direction or vehicle; drop rows with no date or no route/line.
