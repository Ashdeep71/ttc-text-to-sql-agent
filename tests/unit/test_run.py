"""Unit tests for the delay-code builder and the processed-data README."""

import pandas as pd

from transitquery.etl import clean_codes
from transitquery.etl.clean_codes import fix_mojibake
from transitquery.etl.run import build_readme


def test_fix_mojibake_repairs_dash():
    broken = "SAME FAULT â\u0080\u0093 NO INTERVENTION"   # UTF-8 dash read as Latin-1
    assert fix_mojibake(broken) == "SAME FAULT – NO INTERVENTION"


def test_fix_mojibake_leaves_clean_text_alone():
    assert fix_mojibake("DOOR PROBLEMS") == "DOOR PROBLEMS"
    assert fix_mojibake(None) is None


def test_delay_codes_newer_description_wins(tmp_path):
    for mode, rows in {
        "subway": "_id,CODE,DESCRIPTION\n1,EUAC,AIR CONDITIONING\n",
        "bus": "_id,CODE,DESCRIPTION\n1,efb, Body \n",
        "streetcar": "_id,CODE,DESCRIPTION\n1,ETAC,HVAC\n",
    }.items():
        folder = tmp_path / f"ttc-{mode}-delay-data"
        folder.mkdir()
        (folder / "code-descriptions.csv").write_text(rows)
    # Old subway sheet: two header rows, then subway codes in columns C-D and SRT codes in G-H.
    old = pd.DataFrame([
        [None] * 8,
        [None, None, "SUB RMENU CODE", "CODE DESCRIPTION", None, None, "SRT RMENU CODE", "CODE DESCRIPTION"],
        [None, 1, "EUAC", "Air Conditioning (old)", None, 1, "ERAC", "Air Conditioning"],
        [None, 2, "SUL", "Old subway code", None, None, None, None],
    ])
    old.to_excel(tmp_path / clean_codes.OLD_SUBWAY_CODES, header=False, index=False)

    codes = clean_codes.clean(tmp_path).set_index("code")

    assert sorted(codes.index) == ["EFB", "ERAC", "ETAC", "EUAC", "SUL"]
    assert codes.loc["EUAC", "description"] == "AIR CONDITIONING"     # current list beats old sheet
    assert codes.loc["EFB", "description"] == "BODY"
    assert codes.loc["EFB", "mode"] == "bus"
    assert codes.loc["ERAC", "mode"] == "subway"


def test_build_readme_lists_counts_and_drops():
    subway = pd.DataFrame({"occurred_at": pd.to_datetime(["2014-01-01", "2026-08-31"]).tz_localize("America/Toronto")})
    subway.attrs = {"rows_in": 5, "steps": [("exact duplicate", 3)]}
    codes = pd.DataFrame({"code": ["EFB"], "description": ["BODY"], "mode": ["bus"]})

    readme = build_readme({"subway_delays": subway, "delay_codes": codes}, min_year=2014)

    assert "| `subway_delays.csv.gz` | 2 | 2014-01-01 | 2026-08-31 |" in readme
    assert "5 raw rows → 2 kept (40.0%)" in readme
    assert "- exact duplicate: 3" in readme
    assert "https://open.toronto.ca/dataset/ttc-subway-delay-data/" in readme
