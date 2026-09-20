"""Backtest a strategy on a CSV of XAUUSD bars.

    python scripts/run_backtest.py --csv data/XAUUSD_M15.csv --config config.yaml --out results
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.backtest import run_backtest  # noqa: E402
from bot.config import load_config  # noqa: E402
from bot.data import load_csv  # noqa: E402
from bot.strategy import create_strategy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="results")
    ap.add_argument("--from", dest="date_from")
    ap.add_argument("--to", dest="date_to")
    args = ap.parse_args()

    cfg = load_config(args.config)
    df = load_csv(args.csv, cfg.backtest.server_utc_offset)
    if args.date_from:
        df = df[df.time_utc >= args.date_from]
    if args.date_to:
        df = df[df.time_utc < args.date_to]
    df = df.reset_index(drop=True)

    strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
    res = run_backtest(df, strategy, cfg.risk, cfg.backtest)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res.trades.to_csv(out / "trades.csv", index=False)
    res.equity.to_csv(out / "equity.csv", index=False)
    (out / "stats.json").write_text(json.dumps(res.stats, indent=2, default=str))

    print(f"Bars: {len(df):,}  {df.time_utc.iloc[0]} -> {df.time_utc.iloc[-1]} (UTC)")
    for k, v in res.stats.items():
        print(f"  {k:24s} {v}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(res.equity.time_utc, res.equity.balance, linewidth=1.2)
        ax.set_title(f"{cfg.symbol} {cfg.strategy.name} — balance")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "equity.png", dpi=120)
        print(f"Saved {out / 'equity.png'}")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
