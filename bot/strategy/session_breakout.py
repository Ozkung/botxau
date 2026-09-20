"""Asian-range breakout with trend filter — a common XAUUSD intraday setup.

Logic (all hours in UTC):
1. Build the Asian range: high/low of bars in [range_start_utc, range_end_utc).
2. During [trade_start_utc, trade_end_utc) look for the FIRST close beyond
   range +/- buffer (buffer = breakout_buffer_atr * ATR).
3. Trend filter: long only above EMA(trend_ema), short only below it.
4. Skip days whose range is too narrow (noise) or too wide (already moved):
   min_range_atr * ATR <= range width <= max_range_atr * ATR.
5. Stop: ``sl_mode``
     atr        -> sl_atr_mult * ATR
     range      -> distance from close to the opposite side of the range
     range_mid  -> distance from close to the middle of the range
   The final SL distance is clamped to [sl_min_atr, sl_max_atr] * ATR.
6. Target: rr * SL distance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, ema
from .base import Strategy

DEFAULTS = dict(
    range_start_utc=0,
    range_end_utc=7,
    trade_start_utc=7,
    trade_end_utc=16,
    trend_ema=200,
    atr_period=14,
    breakout_buffer_atr=0.1,
    min_range_atr=1.0,
    max_range_atr=6.0,
    sl_mode="atr",
    sl_atr_mult=1.5,
    sl_min_atr=0.8,
    sl_max_atr=3.0,
    rr=2.0,
    allow_long=True,
    allow_short=True,
)


class SessionBreakout(Strategy):
    name = "session_breakout"

    def __init__(self, **params):
        unknown = set(params) - set(DEFAULTS)
        if unknown:
            raise ValueError(f"Unknown session_breakout params: {sorted(unknown)}")
        merged = {**DEFAULTS, **params}
        if not merged["range_start_utc"] < merged["range_end_utc"] <= merged["trade_start_utc"] < merged["trade_end_utc"]:
            raise ValueError("Require range_start < range_end <= trade_start < trade_end (UTC hours, same day)")
        if merged["sl_mode"] not in ("atr", "range", "range_mid"):
            raise ValueError("sl_mode must be atr | range | range_mid")
        super().__init__(**merged)

    @property
    def min_bars(self) -> int:
        return int(max(self.params["trend_ema"], self.params["atr_period"]) + 5)

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = df.copy()
        out["ema"] = ema(out["close"], p["trend_ema"])
        out["atr"] = atr(out, p["atr_period"])

        hour = out["time_utc"].dt.hour
        date = out["time_utc"].dt.normalize()
        in_range = (hour >= p["range_start_utc"]) & (hour < p["range_end_utc"])

        # Range per day, only exposed to bars AFTER the range window has closed
        # (no look-ahead: a bar at 07:00 sees the 00:00-06:59 range only).
        rng = out.loc[in_range].groupby(date[in_range]).agg(r_hi=("high", "max"), r_lo=("low", "min"))
        out["r_hi"] = date.map(rng["r_hi"])
        out["r_lo"] = date.map(rng["r_lo"])
        after_range = hour >= p["range_end_utc"]
        out.loc[~after_range, ["r_hi", "r_lo"]] = np.nan

        width = out["r_hi"] - out["r_lo"]
        a = out["atr"]
        buf = p["breakout_buffer_atr"] * a
        up_lvl = out["r_hi"] + buf
        dn_lvl = out["r_lo"] - buf

        prev_close = out["close"].shift(1)
        same_day = date.eq(date.shift(1))
        in_trade = (hour >= p["trade_start_utc"]) & (hour < p["trade_end_utc"])
        range_ok = (width >= p["min_range_atr"] * a) & (width <= p["max_range_atr"] * a)
        base_ok = in_trade & range_ok & a.notna() & out["ema"].notna()

        # "first cross": previous close (same day) was still inside the level.
        # prev bar may pre-date the range close (e.g. 06:45) — its close is inside the range by construction.
        long_sig = (
            base_ok & same_day
            & (out["close"] > up_lvl) & ~(prev_close > up_lvl)
            & (out["close"] > out["ema"])
        )
        short_sig = (
            base_ok & same_day
            & (out["close"] < dn_lvl) & ~(prev_close < dn_lvl)
            & (out["close"] < out["ema"])
        )
        if not p["allow_long"]:
            long_sig[:] = False
        if not p["allow_short"]:
            short_sig[:] = False

        signal = np.where(long_sig, 1, np.where(short_sig, -1, 0))

        if p["sl_mode"] == "atr":
            sl = p["sl_atr_mult"] * a
        elif p["sl_mode"] == "range":
            sl = pd.Series(np.where(signal > 0, out["close"] - out["r_lo"], out["r_hi"] - out["close"]), index=out.index)
        else:  # range_mid
            mid = (out["r_hi"] + out["r_lo"]) / 2
            sl = (out["close"] - mid).abs()
        sl = sl.clip(lower=p["sl_min_atr"] * a, upper=p["sl_max_atr"] * a)

        out["signal"] = signal
        out["sl_dist"] = np.where(signal != 0, sl, np.nan)
        out["tp_dist"] = out["sl_dist"] * p["rr"]
        out["reason"] = np.where(
            signal > 0, "asia_breakout_up", np.where(signal < 0, "asia_breakout_down", "")
        )
        # A signal with an invalid stop is no signal.
        bad = (out["signal"] != 0) & ~(out["sl_dist"] > 0)
        out.loc[bad, "signal"] = 0
        return out
