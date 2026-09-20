"""Generate SYNTHETIC XAUUSD-like M15 bars so the backtester can be tried without MT5.

Results on synthetic data mean nothing about real profitability — use it only
to check the pipeline works. Real testing needs real broker history
(scripts/fetch_history.py).

    python scripts/make_sample_data.py --days 250 --out data/sample_M15.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def synthetic_bars(days: int = 250, start_price: float = 2400.0, seed: int = 7, server_offset: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-06", periods=days * 96, freq="15min")  # UTC
    idx = idx[idx.dayofweek < 5]
    hours = idx.hour.to_numpy()
    # intraday volatility profile: quiet Asia, active London / NY
    vol = np.where(hours < 7, 0.6, np.where(hours < 12, 1.3, np.where(hours < 17, 1.6, 0.8)))
    base_sigma = 1.6  # USD per 15m bar
    drift = rng.normal(0, 0.03, size=len(idx)).cumsum() * 0.002  # slow regime drift
    rets = rng.normal(0, 1, size=len(idx)) * base_sigma * vol + drift
    close = start_price + np.cumsum(rets)
    open_ = np.concatenate([[start_price], close[:-1]]) + rng.normal(0, 0.05, size=len(idx))
    wick = np.abs(rng.normal(0, 0.8, size=len(idx))) * vol
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.8, size=len(idx))) * vol
    # spread in POINTS (as MT5 writes it): ~0.18-0.32 USD normally, far wider at
    # the 21:00-23:00 UTC rollover and on the occasional news bar
    spread_pts = rng.integers(18, 33, size=len(idx)).astype(float)
    spread_pts *= np.where((hours >= 21) & (hours < 23), rng.uniform(3.0, 8.0, size=len(idx)), 1.0)
    news = rng.random(len(idx)) < 0.01
    spread_pts = np.where(news, spread_pts * rng.uniform(2.0, 6.0, size=len(idx)), spread_pts)
    df = pd.DataFrame({
        "time": idx + pd.Timedelta(hours=server_offset),
        "open": open_.round(2), "high": high.round(2), "low": low.round(2), "close": close.round(2),
        "tick_volume": rng.integers(200, 3000, size=len(idx)),
        "spread": spread_pts.round().astype(int),
    })
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=250)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/sample_M15.csv")
    args = ap.parse_args()
    df = synthetic_bars(args.days, seed=args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Saved {len(df):,} synthetic bars -> {args.out}")


if __name__ == "__main__":
    main()
