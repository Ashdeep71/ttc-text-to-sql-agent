"""Build one delay_codes lookup table from the code lists of all three modes.

Codes are unique across modes: the second letter says which system a code belongs
to (U = subway, R = Scarborough RT, F = bus, T = streetcar). So one table keyed by
`code` works, even though streetcar rows sometimes use bus codes.
"""

import logging

import pandas as pd

from transitquery.etl.common import RAW_DIR, StepLog

logger = logging.getLogger(__name__)

MODES = ("subway", "bus", "streetcar")

# Older subway list: codes that dropped out of code-descriptions.csv but still appear
# in the delay data, plus the Scarborough RT codes. Two side-by-side tables in one sheet.
OLD_SUBWAY_CODES = "ttc-subway-delay-data/ttc-subway-delay-codes.xlsx"


def fix_mojibake(text: str) -> str:
    """Repair UTF-8 text that was decoded as Latin-1: 'FAULT â\\x80\\x93 NO' -> 'FAULT – NO'."""
    if not isinstance(text, str) or "â" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _clean(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    return pd.DataFrame({
        "code": df["code"].astype(str).str.strip().str.upper(),
        "description": df["description"].map(fix_mojibake).astype(str).str.strip().str.upper(),
        "mode": mode,
    })


def read_current(mode: str, raw_dir=RAW_DIR) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / f"ttc-{mode}-delay-data" / "code-descriptions.csv")
    return _clean(df.rename(columns={"CODE": "code", "DESCRIPTION": "description"}), mode)


def read_old_subway(raw_dir=RAW_DIR) -> pd.DataFrame:
    sheet = pd.read_excel(raw_dir / OLD_SUBWAY_CODES, header=None, skiprows=2)
    subway = sheet[[2, 3]].set_axis(["code", "description"], axis=1)
    srt = sheet[[6, 7]].set_axis(["code", "description"], axis=1)
    return _clean(pd.concat([subway, srt]).dropna(), "subway")


def clean(raw_dir=RAW_DIR) -> pd.DataFrame:
    """Current lists first, so their (newer) descriptions win over the old subway list."""
    parts = [read_current(mode, raw_dir) for mode in MODES] + [read_old_subway(raw_dir)]
    df = pd.concat(parts, ignore_index=True)
    log = StepLog("delay_codes", len(df))
    df = log.drop(df, df["code"].duplicated(), "code already listed")
    return log.finish(df.sort_values("code"))
