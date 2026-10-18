"""Strategy plug-in contract.

A strategy receives OHLC bars (bid prices) with a ``time_utc`` column and adds
three columns in ``prepare``:

* ``signal``  : +1 long, -1 short, 0 none — evaluated on the CLOSED bar
* ``sl_dist`` : stop-loss distance in price units (> 0 when signal != 0)
* ``tp_dist`` : take-profit distance in price units (> 0 when signal != 0),
                or NaN for "no take-profit"

Optional exit behaviour a strategy can switch on (both honoured by the
backtester and the live engine):

* ``trail_pct``               : trail the stop this fraction of price behind the
                                best price since entry (None = fixed stop)
* ``trail_step_pct``          : live only — minimum improvement before the SL is
                                modified at the broker
* ``exit_on_opposite_signal`` : an opposite signal closes the open position

``prepare`` must return one row per input bar, in the same order, keeping the
input columns — the backtester aligns its arrays positionally and reads the
per-bar ``spread`` column from them.

Both the backtester and the live engine call exactly the same ``prepare`` so a
strategy behaves identically in simulation and production.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class Signal:
    side: int          # +1 buy, -1 sell
    sl_dist: float
    tp_dist: float
    bar_time_utc: pd.Timestamp
    reason: str = ""

    @property
    def side_name(self) -> str:
        return "BUY" if self.side > 0 else "SELL"


class Strategy(ABC):
    name: str = "base"
    trail_pct: Optional[float] = None
    trail_step_pct: float = 0.0
    exit_on_opposite_signal: bool = False

    def __init__(self, **params):
        self.params = params

    @property
    @abstractmethod
    def min_bars(self) -> int:
        """Bars of history needed before signals are valid."""

    @abstractmethod
    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of df with signal / sl_dist / tp_dist columns."""

    def signal_at(self, prepared: pd.DataFrame, i: int) -> Optional[Signal]:
        row = prepared.iloc[i]
        side = int(row["signal"])
        if side == 0:
            return None
        return Signal(
            side=side,
            sl_dist=float(row["sl_dist"]),
            tp_dist=float(row["tp_dist"]),
            bar_time_utc=row["time_utc"],
            reason=str(row.get("reason", self.name)),
        )
