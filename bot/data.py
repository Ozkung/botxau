"""Load OHLC bars from CSV and normalise to the bot's DataFrame schema.

Schema: time (broker server time, naive), time_utc, open, high, low, close[, tick_volume, spread]

Accepted CSV formats
* bot format (scripts/fetch_history.py): time,open,high,low,close,tick_volume,spread
* MT5 terminal export (History Center / "Export bars"), tab-separated:
  <DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ["open", "high", "low", "close"]


def load_csv(path: str | Path, server_utc_offset: int) -> pd.DataFrame:
    path = Path(path)
    with open(path, "r", encoding="utf-8-sig") as fh:
        head = fh.readline()
    if "<DATE>" in head.upper():
        df = pd.read_csv(path, sep="\t" if "\t" in head else ",")
        df.columns = [c.strip("<>").lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["date"] + " " + df["time"], format="%Y.%m.%d %H:%M:%S", errors="coerce")
        df = df.rename(columns={"tickvol": "tick_volume"})
    else:
        df = pd.read_csv(path)
        df.columns = [c.strip().lower() for c in df.columns]
        df["time"] = pd.to_datetime(df["time"])
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return normalise(df, server_utc_offset)


def normalise(df: pd.DataFrame, server_utc_offset: int) -> pd.DataFrame:
    out = df.dropna(subset=["time", *REQUIRED]).copy()
    out = out.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    out["time_utc"] = out["time"] - pd.Timedelta(hours=int(server_utc_offset))
    for c in REQUIRED:
        out[c] = out[c].astype(float)
    return out
