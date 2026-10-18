"""EMA cross with a percentage trailing stop — a slow trend-following setup.

Logic:
1. Signal on the CLOSED bar where close crosses the EMA:
   prev close <= prev EMA and close > EMA  -> long
   prev close >= prev EMA and close < EMA  -> short
2. Initial stop: ``trail_pct`` of the signal bar's close (e.g. 3% of ~4000 = ~120 USD).
3. No take-profit. The stop trails the best price since entry by ``trail_pct``
   and only ever moves in the trade's favour (backtester and live engine both
   honour ``Strategy.trail_pct``).
4. ``exit_on_cross``: an opposite cross closes the open position at the next
   bar's open (backtest) / immediately (live) before the reverse entry is
   considered, so the bot is never stuck holding against the trend while the
   wide trailing stop is still far away.

Built for H4/D1. With a 3-5% stop the account needs roughly
``price * trail_pct * 100oz * 0.01 lot / risk%`` equity to trade the minimum
lot (~12,000 USD at 4000/3%/1%) — below that every signal is skipped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import ema
from .base import Strategy

DEFAULTS = dict(
    ema_period=200,
    trail_pct=0.03,         # 0.03 = 3% of price
    trail_step_pct=0.001,   # live only: move SL when it improves by >= 0.1% of price (avoids broker spam)
    exit_on_cross=True,
    allow_long=True,
    allow_short=True,
)


class EmaTrail(Strategy):
    name = "ema_trail"

    def __init__(self, **params):
        unknown = set(params) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"Unknown ema_trail params: {sorted(unknown)}")
        merged = {**DEFAULTS, **params}
        if int(merged["ema_period"]) < 2:
            raise ValueError("ema_period must be >= 2")
        if not 0 < float(merged["trail_pct"]) < 0.5:
            raise ValueError("trail_pct must be a fraction between 0 and 0.5 (0.03 = 3%)")
        if not 0 <= float(merged["trail_step_pct"]) < float(merged["trail_pct"]):
            raise ValueError("trail_step_pct must be >= 0 and smaller than trail_pct")
        super().__init__(**merged)
        self.trail_pct = float(merged["trail_pct"])
        self.trail_step_pct = float(merged["trail_step_pct"])
        self.exit_on_opposite_signal = bool(merged["exit_on_cross"])

    @property
    def min_bars(self) -> int:
        return int(self.params["ema_period"]) + 5

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = df.copy()
        out["ema"] = ema(out["close"], int(p["ema_period"]))

        prev_close = out["close"].shift(1)
        prev_ema = out["ema"].shift(1)
        valid = out["ema"].notna() & prev_ema.notna()
        long_sig = valid & (prev_close <= prev_ema) & (out["close"] > out["ema"])
        short_sig = valid & (prev_close >= prev_ema) & (out["close"] < out["ema"])
        if not p["allow_long"]:
            long_sig[:] = False
        if not p["allow_short"]:
            short_sig[:] = False

        signal = np.where(long_sig, 1, np.where(short_sig, -1, 0))
        out["signal"] = signal
        out["sl_dist"] = np.where(signal != 0, out["close"] * self.trail_pct, np.nan)
        out["tp_dist"] = np.nan  # no take-profit: the trailing stop (or the opposite cross) exits
        out["reason"] = np.where(signal > 0, "ema_cross_up", np.where(signal < 0, "ema_cross_down", ""))
        return out
