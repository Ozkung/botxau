"""Live trading engine: poll -> manage open trades -> on new closed bar evaluate strategy -> guards -> order."""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import pandas as pd

from .broker.base import Broker, Position, Tick
from .config import BotConfig
from .data import normalise
from .journal import Journal
from .notifier import Notifier
from .risk import GuardState, check_guards, position_size
from .strategy import Strategy

log = logging.getLogger(__name__)

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


class LiveEngine:
    def __init__(self, cfg: BotConfig, broker: Broker, strategy: Strategy, journal: Journal,
                 notifier: Optional[Notifier] = None):
        self.cfg = cfg
        self.broker = broker
        self.strategy = strategy
        self.journal = journal
        self.notifier = notifier or Notifier(cfg.notify)
        self.last_bar_time: Optional[pd.Timestamp] = None
        self.spec = None
        self.tf_minutes = TF_MINUTES[cfg.timeframe.upper()]
        if cfg.history_bars < strategy.min_bars + 50:
            raise ValueError(f"history_bars must be >= {strategy.min_bars + 50} for this strategy")

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.broker.connect()
        self.spec = self.broker.symbol_spec(self.cfg.symbol)
        mode = "DRY-RUN (no orders)" if self.cfg.dry_run else "LIVE"
        msg = f"XAUUSD bot started [{mode}] symbol={self.cfg.symbol} tf={self.cfg.timeframe} strategy={self.strategy.name}"
        log.info(msg)
        self.notifier.send(msg)
        try:
            while True:
                try:
                    self.step()
                except Exception as exc:  # noqa: BLE001 — keep the loop alive
                    log.exception("step failed: %s", exc)
                    self.journal.event("ERROR", repr(exc))
                    time.sleep(max(self.cfg.poll_seconds, 15))
                time.sleep(self.cfg.poll_seconds)
        except KeyboardInterrupt:
            log.info("Stopped by user")
        finally:
            self.broker.shutdown()

    # ------------------------------------------------------------------
    def _offset(self) -> int:
        if isinstance(self.cfg.server_utc_offset, int):
            return self.cfg.server_utc_offset
        return self.broker.server_utc_offset_hours(self.cfg.symbol)

    def step(self) -> Optional[str]:
        """One polling iteration. Returns a short status string (useful for tests/logs)."""
        if self.spec is None:
            self.spec = self.broker.symbol_spec(self.cfg.symbol)
        offset = self._offset()
        tick = self.broker.tick(self.cfg.symbol)
        now_utc = tick.time_server - pd.Timedelta(hours=offset)
        positions = self.broker.positions(self.cfg.symbol, self.cfg.magic)
        self._manage(positions, tick, now_utc)

        bars = normalise(self.broker.closed_bars(self.cfg.symbol, self.cfg.timeframe, self.cfg.history_bars), offset)
        if len(bars) < self.strategy.min_bars:
            return "not enough bars"
        last_time = bars["time_utc"].iloc[-1]
        if self.last_bar_time is not None and last_time <= self.last_bar_time:
            return "no new bar"
        self.last_bar_time = last_time

        prepared = self.strategy.prepare(bars)
        sig = self.strategy.signal_at(prepared, len(prepared) - 1)
        if sig is None:
            return "no signal"

        bar_close_utc = sig.bar_time_utc + pd.Timedelta(minutes=self.tf_minutes)
        if now_utc - bar_close_utc > pd.Timedelta(minutes=self.tf_minutes):
            return "stale signal"
        bar_key = sig.bar_time_utc.isoformat()
        if self.journal.already_traded_bar(bar_key):
            return "already traded"

        date_utc = now_utc.strftime("%Y-%m-%d")
        equity = self.broker.equity()
        guard = check_guards(
            GuardState(
                equity=equity,
                day_start_equity=self.journal.day_start_equity(date_utc, equity),
                trades_today=self.journal.trades_on(date_utc),
                open_positions=len(positions),
                spread=tick.spread,
                hour_utc=now_utc.hour,
                kill_switch=os.path.exists(self.cfg.kill_switch_file),
            ),
            self.cfg.risk,
        )
        if guard:
            log.info("Signal %s blocked: %s", sig.side_name, guard)
            self.journal.event("INFO", f"signal {sig.side_name} @ {bar_key} blocked: {guard}")
            return f"blocked: {guard}"

        sl_dist, tp_dist = sig.sl_dist, sig.tp_dist
        min_dist = self.spec.stops_level * 1.1
        if sl_dist < min_dist:  # broker minimum stop distance
            scale = min_dist / sl_dist
            sl_dist, tp_dist = sl_dist * scale, tp_dist * scale
        lots = position_size(equity, self.cfg.risk.risk_per_trade_pct, sl_dist, self.spec)
        if lots <= 0:
            self.journal.event("INFO", f"signal {sig.side_name} skipped: lot below minimum")
            return "blocked: lot below minimum"

        price = tick.ask if sig.side > 0 else tick.bid
        sl = round(price - sig.side * sl_dist, self.spec.digits)
        tp = round(price + sig.side * tp_dist, self.spec.digits)
        comment = f"xau-bot {self.strategy.name}"[:31]

        if self.cfg.dry_run:
            ok, ticket, fill, message = True, None, price, "DRY_RUN"
        else:
            res = self.broker.market_order(self.cfg.symbol, sig.side, lots, sl, tp, self.cfg.magic, comment)
            ok, ticket, fill, message = res.ok, res.ticket, res.price or price, res.message

        self.journal.record_entry(
            date_utc=date_utc, signal_bar_utc=bar_key, side=sig.side_name, lots=lots, price=fill,
            sl=sl, tp=tp, ticket=ticket, dry_run=self.cfg.dry_run, ok=ok, message=message, reason=sig.reason,
        )
        text = (f"{'[DRY] ' if self.cfg.dry_run else ''}{sig.side_name} {self.cfg.symbol} {lots} lot @ {fill:.2f} "
                f"SL {sl:.2f} TP {tp:.2f} ({sig.reason}) -> {'OK' if ok else 'FAILED'} {message}")
        (log.info if ok else log.error)(text)
        self.notifier.send(text)
        return "order sent" if ok else f"order failed: {message}"

    # ------------------------------------------------------------------
    def _manage(self, positions: list[Position], tick: Tick, now_utc: pd.Timestamp) -> None:
        risk = self.cfg.risk
        for p in positions:
            if risk.force_close_utc is not None and now_utc.hour >= risk.force_close_utc:
                if self.cfg.dry_run:
                    continue
                res = self.broker.close_position(self.cfg.symbol, p, self.cfg.magic)
                self._report(f"Force-close #{p.ticket}", res.ok, res.message)
                continue
            if not risk.breakeven_at_r or self.cfg.dry_run:
                continue
            if p.side > 0 and 0 < p.sl < p.price_open:
                if tick.bid - p.price_open >= risk.breakeven_at_r * (p.price_open - p.sl):
                    res = self.broker.modify_sltp(self.cfg.symbol, p.ticket, p.price_open, p.tp)
                    self._report(f"Breakeven #{p.ticket}", res.ok, res.message)
            elif p.side < 0 and p.sl > p.price_open:
                if p.price_open - tick.ask >= risk.breakeven_at_r * (p.sl - p.price_open):
                    res = self.broker.modify_sltp(self.cfg.symbol, p.ticket, p.price_open, p.tp)
                    self._report(f"Breakeven #{p.ticket}", res.ok, res.message)

    def _report(self, what: str, ok: bool, message: str) -> None:
        text = f"{what}: {'OK' if ok else 'FAILED'} {message}"
        (log.info if ok else log.error)(text)
        self.journal.event("INFO" if ok else "ERROR", text)
        self.notifier.send(text)
