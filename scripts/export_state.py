"""Dump the bot's current state as JSON - for the desktop app or any other tool.

    python scripts/export_state.py --config config.yaml

Reads config.yaml and the SQLite journal only. It never touches MT5, so it
works on any OS, whether or not the bot is currently running, and it opens
the database read-only so it cannot corrupt a journal the live engine has
open at the same time.

Exit code is 0 even when config.yaml is missing or broken - the JSON has a
"config_error" field for that instead, so a caller gets one shape of output
to parse either way. A malformed journal file is the one thing that still
raises, since at that point there is nothing useful to report.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.config import load_config  # noqa: E402


def read_journal(path: str, limit: int) -> dict:
    if not Path(path).exists():
        return {"entries": [], "day_state": [], "events": []}
    # read-only: never blocks on, or is blocked by, a live engine that has
    # the same file open for writing
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        entries = [dict(r) for r in db.execute(
            "SELECT * FROM entries ORDER BY id DESC LIMIT ?", (limit,))]
        day_state = [dict(r) for r in db.execute(
            "SELECT * FROM day_state ORDER BY date_utc DESC LIMIT 30")]
        events = [dict(r) for r in db.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        db.close()
    return {"entries": entries, "day_state": day_state, "events": events}


def build_state(config_path: str, limit: int) -> dict:
    out: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        cfg = load_config(config_path)
    except Exception as exc:  # missing file, bad YAML, unknown key, ...
        out["config_error"] = str(exc)
        return out

    out["config"] = {
        "symbol": cfg.symbol,
        "timeframe": cfg.timeframe,
        "magic": cfg.magic,
        "dry_run": cfg.dry_run,
        "strategy": cfg.strategy.name,
        "risk_per_trade_pct": cfg.risk.risk_per_trade_pct,
        "max_daily_loss_pct": cfg.risk.max_daily_loss_pct,
        "max_trades_per_day": cfg.risk.max_trades_per_day,
        "max_open_positions": cfg.risk.max_open_positions,
        "max_spread": cfg.risk.max_spread,
        "kill_switch_file": cfg.kill_switch_file,
        "journal_path": cfg.journal_path,
        "server_utc_offset": cfg.backtest.server_utc_offset,
        # Non-secret only: a GUI can show these back to the user. Password
        # and Telegram token are write-only from the GUI's point of view -
        # never round-tripped back into a form.
        "mt5_path": cfg.mt5.path,
        "mt5_login": cfg.mt5.login,
        "mt5_server": cfg.mt5.server,
        "mt5_password_set": bool(cfg.mt5.password),
        "telegram_chat_id": cfg.notify.telegram_chat_id,
        "telegram_token_set": bool(cfg.notify.telegram_token),
    }
    out["kill_switch_active"] = Path(cfg.kill_switch_file).exists()

    try:
        out.update(read_journal(cfg.journal_path, limit))
    except sqlite3.DatabaseError as exc:
        out["journal_error"] = f"{cfg.journal_path}: {exc}"
        out.setdefault("entries", []), out.setdefault("day_state", []), out.setdefault("events", [])

    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out["today"] = next((d for d in out["day_state"] if d["date_utc"] == today_key), None)
    out["trades_today"] = sum(1 for e in out["entries"] if e["date_utc"] == today_key and e["ok"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--limit", type=int, default=50, help="max rows per table")
    args = ap.parse_args()

    state = build_state(args.config, args.limit)
    print(json.dumps(state, default=str))
    return 0  # a broken config/journal is reported IN the JSON, not via exit code


if __name__ == "__main__":
    raise SystemExit(main())
