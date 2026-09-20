"""Config loading — YAML -> dataclasses (typed, with defaults)."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Optional, Union

import yaml


@dataclass
class MT5Config:
    path: Optional[str] = None       # terminal64.exe path (None = default install)
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None


@dataclass
class StrategyConfig:
    name: str = "session_breakout"
    params: dict = field(default_factory=dict)


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.5     # % of equity risked per trade
    max_daily_loss_pct: float = 2.0     # stop trading for the UTC day after this drawdown
    max_trades_per_day: int = 2
    max_open_positions: int = 1
    max_spread: float = 0.40            # price units (USD) — XAUUSD 0.40 = 40 points on 2-digit
    breakeven_at_r: Optional[float] = 1.0   # move SL to entry after +1R (None = off)
    force_close_utc: Optional[int] = 20     # close all positions at/after this UTC hour (None = off)


@dataclass
class BacktestConfig:
    initial_balance: float = 10_000.0
    spread: float = 0.25                # assumed constant spread (price units)
    commission_per_lot: float = 7.0     # round-trip USD per 1.00 lot
    contract_size: float = 100.0        # 1 lot XAUUSD = 100 oz
    volume_min: float = 0.01
    volume_step: float = 0.01
    volume_max: float = 50.0
    server_utc_offset: int = 2          # hours; CSV timestamps are broker-server time


@dataclass
class NotifyConfig:
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


@dataclass
class BotConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M15"
    magic: int = 20260920
    dry_run: bool = True                # True = log signals only, never send orders
    poll_seconds: int = 5
    history_bars: int = 600
    server_utc_offset: Union[str, int] = "auto"
    journal_path: str = "data/journal.sqlite"
    kill_switch_file: str = "STOP"      # create this file to block new entries
    mt5: MT5Config = field(default_factory=MT5Config)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)


_NESTED = {
    "mt5": MT5Config,
    "strategy": StrategyConfig,
    "risk": RiskConfig,
    "backtest": BacktestConfig,
    "notify": NotifyConfig,
}


def _build(cls, data: dict[str, Any]):
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown config keys for {cls.__name__}: {sorted(unknown)}")
    return cls(**data)


def load_config(path: Union[str, Path, None] = None) -> BotConfig:
    raw: dict[str, Any] = {}
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key in _NESTED:
            kwargs[key] = _build(_NESTED[key], value or {})
        else:
            kwargs[key] = value
    return _build(BotConfig, kwargs)
