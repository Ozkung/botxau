"""Position sizing and pre-trade guards — shared by backtest and live."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .config import RiskConfig


@dataclass(frozen=True)
class SymbolSpec:
    contract_size: float = 100.0   # oz per lot for XAUUSD
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 50.0
    digits: int = 2
    stops_level: float = 0.0      # min SL/TP distance from price, in price units


def position_size(equity: float, risk_pct: float, sl_dist: float, spec: SymbolSpec) -> float:
    """Lots such that hitting SL loses ~risk_pct of equity (rounded DOWN).

    Returns 0.0 when even the minimum lot would exceed the risk budget —
    the caller must skip the trade rather than over-risk.
    """
    if equity <= 0 or sl_dist <= 0 or risk_pct <= 0:
        return 0.0
    risk_usd = equity * risk_pct / 100.0
    raw = risk_usd / (sl_dist * spec.contract_size)
    steps = math.floor(raw / spec.volume_step + 1e-9)
    lots = round(steps * spec.volume_step, 8)
    if lots < spec.volume_min:
        return 0.0
    return min(lots, spec.volume_max)


@dataclass
class GuardState:
    equity: float
    day_start_equity: float
    trades_today: int
    open_positions: int
    spread: float
    hour_utc: int
    kill_switch: bool = False


def check_guards(state: GuardState, cfg: RiskConfig) -> Optional[str]:
    """Return a reason string if a NEW entry is blocked, else None."""
    if state.kill_switch:
        return "kill switch active"
    if state.day_start_equity > 0:
        dd_pct = (state.day_start_equity - state.equity) / state.day_start_equity * 100
        if dd_pct >= cfg.max_daily_loss_pct:
            return f"daily loss limit hit ({dd_pct:.2f}% >= {cfg.max_daily_loss_pct}%)"
    if state.trades_today >= cfg.max_trades_per_day:
        return f"max trades/day reached ({state.trades_today})"
    if state.open_positions >= cfg.max_open_positions:
        return f"max open positions reached ({state.open_positions})"
    if state.spread > cfg.max_spread:
        return f"spread too wide ({state.spread:.2f} > {cfg.max_spread})"
    if cfg.force_close_utc is not None and state.hour_utc >= cfg.force_close_utc:
        return "past force-close hour"
    return None
