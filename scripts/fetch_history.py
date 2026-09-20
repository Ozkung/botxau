"""Download XAUUSD history from MT5 into a CSV for backtesting (Windows).

    python scripts/fetch_history.py --config config.yaml --from 2023-01-01 --to 2026-09-01 --out data/XAUUSD_M15.csv

Tip: in MT5 set Tools > Options > Charts > "Max bars in chart" to Unlimited,
otherwise the terminal may return fewer bars than requested.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.broker.mt5_broker import MT5Broker, _tf, mt5  # noqa: E402
from bot.config import load_config  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    broker = MT5Broker(cfg.mt5)
    broker.connect()
    try:
        broker.symbol_spec(cfg.symbol)  # symbol_select
        rates = mt5.copy_rates_range(
            cfg.symbol, _tf(cfg.timeframe),
            datetime.fromisoformat(args.date_from), datetime.fromisoformat(args.date_to),
        )
        if rates is None or len(rates) == 0:
            raise SystemExit(f"No data returned: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df[["time", "open", "high", "low", "close", "tick_volume", "spread"]].to_csv(args.out, index=False)
        print(f"Saved {len(df):,} bars -> {args.out}  ({df.time.iloc[0]} .. {df.time.iloc[-1]} server time)")
    finally:
        broker.shutdown()


if __name__ == "__main__":
    main()
