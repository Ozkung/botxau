"""Run the bot against MetaTrader 5 (Windows).

    python scripts/run_live.py --config config.yaml

Keep ``dry_run: true`` until you have watched it on a demo account for weeks.
Create a file named STOP in the working directory to block new entries.
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.broker.mt5_broker import MT5Broker  # noqa: E402
from bot.config import load_config  # noqa: E402
from bot.engine import LiveEngine  # noqa: E402
from bot.journal import Journal  # noqa: E402
from bot.strategy import create_strategy  # noqa: E402


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler("logs/bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    setup_logging()

    cfg = load_config(args.config)
    fallback = cfg.server_utc_offset if isinstance(cfg.server_utc_offset, int) else cfg.backtest.server_utc_offset
    broker = MT5Broker(cfg.mt5, fallback_utc_offset=fallback)
    strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
    engine = LiveEngine(cfg, broker, strategy, Journal(cfg.journal_path))
    engine.run()


if __name__ == "__main__":
    main()
