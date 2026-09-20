from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot.backtest import run_backtest  # noqa: E402
from bot.broker.base import Broker, OrderResult, Position, Tick  # noqa: E402
from bot.config import BacktestConfig, BotConfig, RiskConfig, load_config  # noqa: E402
from bot.data import normalise  # noqa: E402
from bot.engine import LiveEngine  # noqa: E402
from bot.journal import Journal  # noqa: E402
from bot.risk import GuardState, SymbolSpec, check_guards, position_size  # noqa: E402
from bot.strategy import create_strategy  # noqa: E402
from make_sample_data import synthetic_bars  # noqa: E402

SPEC = SymbolSpec()
# small EMA so the scenario needs few warm-up bars
PARAMS = dict(trend_ema=20, atr_period=5, min_range_atr=0.5, max_range_atr=20, sl_mode="atr",
              sl_atr_mult=1.0, sl_min_atr=0.1, sl_max_atr=10, rr=2.0, breakout_buffer_atr=0.0)


def scenario(breakout_close: float = 2012.0, after: list[float] | None = None) -> pd.DataFrame:
    """Two days of M15 bars: day 1 warm-up uptrend; day 2 range 2000-2010 then breakout."""
    rows = []
    t0 = pd.Timestamp("2026-01-05 16:00")  # warm-up after day-1 trade window -> no day-1 signals
    price = 1996.8
    for k in range(32):  # day 1 evening, gently rising
        t = t0 + pd.Timedelta(minutes=15 * k)
        o, c = price, price + 0.1
        rows.append((t, o, c + 0.5, o - 0.5, c))
        price = c
    d2 = pd.Timestamp("2026-01-06 00:00")
    for k in range(28):  # 00:00-06:45 range between 2000 and 2010
        t = d2 + pd.Timedelta(minutes=15 * k)
        c = 2005.0 + (2 if k % 2 else -2)
        rows.append((t, 2005.0, 2010.0 if k == 5 else c + 1, 2000.0 if k == 9 else c - 1, c))
    t = d2 + pd.Timedelta(hours=7)
    rows.append((t, 2006.0, breakout_close + 0.5, 2005.5, breakout_close))  # 07:00 breakout bar
    for k, c in enumerate(after or [], start=1):
        tt = t + pd.Timedelta(minutes=15 * k)
        prev = rows[-1][4]
        rows.append((tt, prev, max(prev, c) + 0.3, min(prev, c) - 0.3, c))
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"])
    return normalise(df, server_utc_offset=0)


# --- risk -----------------------------------------------------------------
def test_position_size_basic():
    # $10k * 0.5% = $50 risk, SL $5 * 100oz = $500/lot -> 0.10 lot
    assert position_size(10_000, 0.5, 5.0, SPEC) == pytest.approx(0.10)


def test_position_size_rounds_down_and_min_lot():
    assert position_size(10_000, 0.5, 7.0, SPEC) == pytest.approx(0.07)  # 0.0714 -> 0.07
    assert position_size(100, 0.5, 10.0, SPEC) == 0.0  # would need 0.0005 lot


def test_guards():
    cfg = RiskConfig()
    ok = GuardState(equity=10_000, day_start_equity=10_000, trades_today=0, open_positions=0, spread=0.2, hour_utc=8)
    assert check_guards(ok, cfg) is None
    assert "daily loss" in check_guards(GuardState(**{**ok.__dict__, "equity": 9_790}), cfg)
    assert "spread" in check_guards(GuardState(**{**ok.__dict__, "spread": 0.9}), cfg)
    assert "max trades" in check_guards(GuardState(**{**ok.__dict__, "trades_today": 2}), cfg)
    assert "kill switch" in check_guards(GuardState(**{**ok.__dict__, "kill_switch": True}), cfg)


# --- strategy -------------------------------------------------------------
def test_breakout_long_signal_on_first_close_above_range():
    s = create_strategy("session_breakout", PARAMS)
    out = s.prepare(scenario(2012.0, after=[2013.0]))
    sig_rows = out[out.signal != 0]
    assert len(sig_rows) == 1  # only the FIRST close above the range
    row = sig_rows.iloc[0]
    assert row.signal == 1
    assert row.time_utc == pd.Timestamp("2026-01-06 07:00")
    assert row.r_hi == 2010.0 and row.r_lo == 2000.0
    assert row.tp_dist == pytest.approx(row.sl_dist * 2)


def test_no_signal_inside_range_or_against_trend():
    s = create_strategy("session_breakout", PARAMS)
    assert (s.prepare(scenario(2008.0)).signal == 0).all()
    shorts_only = create_strategy("session_breakout", {**PARAMS, "allow_long": False})
    assert (shorts_only.prepare(scenario(2012.0)).signal == 0).all()


def test_no_lookahead_range_not_visible_during_range():
    s = create_strategy("session_breakout", PARAMS)
    out = s.prepare(scenario(2012.0))
    during = out[(out.time_utc.dt.date == pd.Timestamp("2026-01-06").date()) & (out.time_utc.dt.hour < 7)]
    assert during.r_hi.isna().all()


def test_invalid_session_hours_rejected():
    with pytest.raises(ValueError):
        create_strategy("session_breakout", {"range_start_utc": 5, "range_end_utc": 3})


# --- backtest -------------------------------------------------------------
def _bt_cfg(**kw):
    return BacktestConfig(**{"spread": 0.2, "commission_per_lot": 0.0, **kw})


def test_backtest_take_profit():
    s = create_strategy("session_breakout", PARAMS)
    df = scenario(2012.0, after=[2014, 2018, 2025, 2040])
    res = run_backtest(df, s, RiskConfig(breakeven_at_r=None, force_close_utc=None), _bt_cfg())
    assert res.stats["trades"] == 1
    t = res.trades.iloc[0]
    assert t.side == 1 and t.exit_reason == "tp"
    assert t.entry == pytest.approx(df.open.iloc[-4] + 0.2)  # next bar open + spread
    assert t.r_multiple == pytest.approx(2.0)
    assert t.pnl > 0


def test_backtest_stop_loss_is_conservative():
    s = create_strategy("session_breakout", PARAMS)
    df = scenario(2012.0, after=[2012.2, 1990.0])
    res = run_backtest(df, s, RiskConfig(breakeven_at_r=None, force_close_utc=None), _bt_cfg())
    t = res.trades.iloc[0]
    assert t.exit_reason == "sl"
    assert t.r_multiple <= -1.0 + 1e-9  # never better than -1R


def test_backtest_runs_on_synthetic_year():
    cfg = load_config(ROOT / "config.example.yaml")
    df = normalise(synthetic_bars(days=200, seed=3), 2)
    s = create_strategy(cfg.strategy.name, cfg.strategy.params)
    res = run_backtest(df, s, cfg.risk, cfg.backtest)
    assert res.stats["trades"] > 20
    tr = res.trades
    assert (tr.lots > 0).all()
    # risk per trade never exceeds budget (loss capped at ~-1R plus commission)
    assert tr.r_multiple.min() >= -1.5
    # at most N trades per UTC day
    assert tr.groupby(tr.entry_time.dt.date).size().max() <= cfg.risk.max_trades_per_day


# --- live engine with a fake broker ---------------------------------------
class FakeBroker(Broker):
    def __init__(self, bars: pd.DataFrame, bid: float, spread: float = 0.2, equity: float = 10_000):
        self.bars, self.bid, self.spread_, self._equity = bars, bid, spread, equity
        self.orders: list[dict] = []
        self.pos: list[Position] = []
        self.modified: list[tuple] = []

    def connect(self): pass
    def shutdown(self): pass
    def symbol_spec(self, symbol): return SymbolSpec(stops_level=0.5)
    def closed_bars(self, symbol, timeframe, count): return self.bars[["time", "open", "high", "low", "close"]].tail(count)

    def tick(self, symbol):
        t = self.bars.time.iloc[-1] + pd.Timedelta(minutes=15, seconds=3)
        return Tick(self.bid, self.bid + self.spread_, t)

    def equity(self): return self._equity
    def server_utc_offset_hours(self, symbol): return 0
    def positions(self, symbol, magic): return list(self.pos)

    def market_order(self, symbol, side, lots, sl, tp, magic, comment):
        self.orders.append(dict(side=side, lots=lots, sl=sl, tp=tp))
        return OrderResult(True, 123, self.bid + (self.spread_ if side > 0 else 0), "retcode=10009 done")

    def modify_sltp(self, symbol, ticket, sl, tp):
        self.modified.append((ticket, sl, tp))
        return OrderResult(True, ticket, None, "ok")

    def close_position(self, symbol, position, magic): return OrderResult(True, position.ticket, None, "ok")


def _engine(broker, dry_run=False, **risk):
    cfg = BotConfig(dry_run=dry_run, server_utc_offset=0, history_bars=200, kill_switch_file="__no_such_file__",
                    risk=RiskConfig(**risk))
    s = create_strategy("session_breakout", PARAMS)
    return LiveEngine(cfg, broker, s, Journal(":memory:"))


def test_engine_places_order_with_correct_size():
    b = FakeBroker(scenario(2012.0), bid=2012.0)
    eng = _engine(b)
    assert eng.step() == "order sent"
    o = b.orders[0]
    sl_dist = 2012.2 - o["sl"]
    assert o["side"] == 1 and sl_dist > 0
    assert o["tp"] - 2012.2 == pytest.approx(2 * sl_dist, abs=0.02)
    assert o["lots"] == position_size(10_000, 0.5, sl_dist, SPEC) or abs(o["lots"] - position_size(10_000, 0.5, sl_dist, SPEC)) <= 0.01
    # same bar again -> no duplicate order
    assert eng.step() == "no new bar"
    assert len(b.orders) == 1


def test_engine_dry_run_sends_nothing():
    b = FakeBroker(scenario(2012.0), bid=2012.0)
    assert _engine(b, dry_run=True).step() == "order sent"
    assert b.orders == []


def test_engine_blocks_on_wide_spread_and_daily_loss():
    b = FakeBroker(scenario(2012.0), bid=2012.0, spread=1.5)
    assert _engine(b).step().startswith("blocked: spread")
    b2 = FakeBroker(scenario(2012.0), bid=2012.0)
    eng = _engine(b2)
    date = (b2.bars.time.iloc[-1] + pd.Timedelta(minutes=15)).strftime("%Y-%m-%d")
    eng.journal.day_start_equity(date, 10_500)  # already down 4.8% today
    assert eng.step().startswith("blocked: daily loss")
    assert b2.orders == []


def test_engine_moves_stop_to_breakeven():
    b = FakeBroker(scenario(2008.0), bid=2016.0)  # no new signal; open long in profit
    b.pos = [Position(ticket=7, side=1, lots=0.1, price_open=2010.0, sl=2005.0, tp=2020.0,
                      time_server=pd.Timestamp("2026-01-06 07:15"))]
    _engine(b, breakeven_at_r=1.0, force_close_utc=None).step()
    assert b.modified == [(7, 2010.0, 2020.0)]
