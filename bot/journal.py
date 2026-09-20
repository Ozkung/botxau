"""SQLite trade journal + small persistent state (survives bot restarts)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL,
    date_utc TEXT NOT NULL,
    signal_bar_utc TEXT NOT NULL,
    side TEXT NOT NULL,
    lots REAL NOT NULL,
    price REAL,
    sl REAL,
    tp REAL,
    ticket INTEGER,
    dry_run INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    message TEXT,
    reason TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_entries_bar ON entries(signal_bar_utc, side) WHERE ok = 1;
CREATE TABLE IF NOT EXISTS day_state (
    date_utc TEXT PRIMARY KEY,
    start_equity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Journal:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def day_start_equity(self, date_utc: str, current_equity: float) -> float:
        row = self.db.execute("SELECT start_equity FROM day_state WHERE date_utc=?", (date_utc,)).fetchone()
        if row:
            return float(row[0])
        self.db.execute("INSERT INTO day_state(date_utc, start_equity) VALUES (?, ?)", (date_utc, current_equity))
        self.db.commit()
        return current_equity

    def trades_on(self, date_utc: str) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM entries WHERE date_utc=? AND ok=1", (date_utc,)).fetchone()
        return int(row[0])

    def already_traded_bar(self, signal_bar_utc: str) -> bool:
        row = self.db.execute("SELECT 1 FROM entries WHERE signal_bar_utc=? AND ok=1", (signal_bar_utc,)).fetchone()
        return row is not None

    def record_entry(self, *, date_utc: str, signal_bar_utc: str, side: str, lots: float,
                     price: Optional[float], sl: float, tp: float, ticket: Optional[int],
                     dry_run: bool, ok: bool, message: str, reason: str) -> None:
        self.db.execute(
            "INSERT INTO entries(created_utc,date_utc,signal_bar_utc,side,lots,price,sl,tp,ticket,dry_run,ok,message,reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_now(), date_utc, signal_bar_utc, side, lots, price, sl, tp, ticket, int(dry_run), int(ok), message, reason),
        )
        self.db.commit()

    def event(self, level: str, message: str) -> None:
        self.db.execute("INSERT INTO events(created_utc, level, message) VALUES (?,?,?)", (_now(), level, message))
        self.db.commit()
