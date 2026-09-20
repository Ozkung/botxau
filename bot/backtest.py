"""Bar-by-bar backtester.

Execution model (deliberately conservative):
* Bars are BID prices. Longs enter at ask (= open + spread), exit at bid.
  Shorts enter at bid, exit at ask (= price + spread).
* Spread is per bar when the CSV carries a ``spread`` column (MT5 writes it in
  POINTS), otherwise the fixed ``backtest.spread``. The same value feeds the
  max-spread guard, so backtest and live block the same wide-spread bars.
* Signal on bar i's close -> market entry at bar i+1's open.
* SL/TP checked on bar high/low. If both are touched in the same bar, SL wins.
* Gaps through SL/TP fill at the bar open (slippage in your disfavour for SL).
* Breakeven is applied at the end of a bar (cannot help within the same bar).
* Force-close at the open of the first bar whose UTC hour >= force_close_utc.
* Daily loss guard uses realised balance vs balance at UTC-day start.
* The equity curve is marked to market every bar at the WORST price the bar
  traded through, so drawdown counts what an open position went through and
  not only what was realised on close.
* R multiples are NET of commission, matching `pnl`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .config import BacktestConfig, RiskConfig
from .risk import GuardState, SymbolSpec, check_guards, position_size
from .strategy import Strategy


@dataclass
class Trade:
    side: int
    entry_time: pd.Timestamp
    entry: float
    sl: float
    tp: float
    lots: float
    risk_dist: float
    initial_sl: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    r_multiple: float = 0.0
    reason: str = ""


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    stats: dict


def spread_per_bar(data: pd.DataFrame, bt: BacktestConfig) -> tuple[np.ndarray, dict]:
    """Per-bar spread in price units, plus a description of what was used.

    MT5 records the ``spread`` column in POINTS, so it is scaled by
    ``10**-digits`` (XAUUSD 2-digit: 25 points = $0.25). Bars whose value is
    missing or non-positive fall back to ``bt.spread``.
    """
    n = len(data)
    fixed = np.full(n, float(bt.spread), dtype=float)
    if bt.spread_source == "fixed" or "spread" not in data.columns:
        why = "fixed" if bt.spread_source == "fixed" else "fixed (no spread column in CSV)"
        return fixed, {"source": why, "median": round(float(bt.spread), 4)}

    points = pd.to_numeric(data["spread"], errors="coerce").to_numpy(dtype=float)
    values = points * (10.0 ** -int(bt.digits))
    bad = ~np.isfinite(values) | (values <= 0)
    values = np.where(bad, fixed, values)
    if bad.all():
        return values, {"source": "fixed (spread column unusable)", "median": round(float(bt.spread), 4)}
    return values, {
        "source": f"csv column (points, digits={bt.digits})",
        "median": round(float(np.median(values)), 4),
        "max": round(float(values.max()), 4),
        "bars_without_spread": int(bad.sum()),
    }


def run_backtest(df: pd.DataFrame, strategy: Strategy, risk: RiskConfig, bt: BacktestConfig) -> BacktestResult:
    data = strategy.prepare(df)
    n = len(data)
    if n != len(df):  # prepare() must keep one row per input bar — everything below is positional
        raise ValueError(f"{strategy.name}.prepare() returned {n} rows for {len(df)} bars")
    o = data["open"].to_numpy()
    h = data["high"].to_numpy()
    lo = data["low"].to_numpy()
    sig = data["signal"].to_numpy()
    sl_d = data["sl_dist"].to_numpy()
    tp_d = data["tp_dist"].to_numpy()
    reasons = data["reason"].to_numpy()
    t_utc = data["time_utc"]
    hours = t_utc.dt.hour.to_numpy()
    days = t_utc.dt.normalize().to_numpy()
    times = t_utc.to_numpy()
    # read spread off the raw input: a strategy that drops the column must not
    # silently downgrade the simulation to a fixed spread
    spread, spread_info = spread_per_bar(df, bt)

    spec = SymbolSpec(
        contract_size=bt.contract_size,
        volume_min=bt.volume_min,
        volume_step=bt.volume_step,
        volume_max=bt.volume_max,
        digits=bt.digits,
    )
    balance = bt.initial_balance
    # (time, realised balance, mark-to-market equity)
    equity_rows: list[tuple] = [(times[0], balance, balance)] if n else []
    trades: list[Trade] = []
    pos: Optional[Trade] = None
    pending: Optional[int] = None  # index of bar that produced the signal
    cur_day = None
    day_start_bal = balance
    trades_today = 0
    skipped: dict[str, int] = {}

    def close(trade: Trade, price: float, when, why: str):
        nonlocal balance
        gross = (price - trade.entry) * trade.side * trade.lots * spec.contract_size
        commission = bt.commission_per_lot * trade.lots
        trade.exit, trade.exit_time, trade.exit_reason = price, pd.Timestamp(when), why
        trade.pnl = gross - commission
        # R is net of costs, so a stop-out is slightly worse than -1R
        trade.r_multiple = trade.pnl / (trade.risk_dist * trade.lots * spec.contract_size)
        balance += trade.pnl
        trades.append(trade)

    for j in range(strategy.min_bars, n):
        if days[j] != cur_day:
            cur_day, day_start_bal, trades_today = days[j], balance, 0

        # 1) execute pending entry at this bar's open
        if pending is not None and pos is None:
            i = pending
            side = int(sig[i])
            entry = o[j] + spread[j] if side > 0 else o[j]
            lots = position_size(balance, risk.risk_per_trade_pct, sl_d[i], spec)
            if lots > 0:
                pos = Trade(
                    side=side, entry_time=pd.Timestamp(times[j]), entry=entry,
                    sl=entry - side * sl_d[i], tp=entry + side * tp_d[i],
                    lots=lots, risk_dist=sl_d[i], reason=str(reasons[i]),
                )
                pos.initial_sl = pos.sl
                trades_today += 1
            else:
                skipped["lot below minimum"] = skipped.get("lot below minimum", 0) + 1
        pending = None

        # 2) manage open position within this bar
        if pos is not None:
            if risk.force_close_utc is not None and hours[j] >= risk.force_close_utc and pos.entry_time < pd.Timestamp(times[j]):
                px = o[j] if pos.side > 0 else o[j] + spread[j]
                close(pos, px, times[j], "force_close")
                pos = None
            else:
                if pos.side > 0:  # long: exits on bid
                    hit_sl = lo[j] <= pos.sl
                    hit_tp = h[j] >= pos.tp
                    if hit_sl:
                        close(pos, min(o[j], pos.sl), times[j], "sl" if pos.sl < pos.entry else "be")
                        pos = None
                    elif hit_tp:
                        close(pos, max(o[j], pos.tp), times[j], "tp")
                        pos = None
                else:  # short: exits on ask
                    ask_h, ask_l, ask_o = h[j] + spread[j], lo[j] + spread[j], o[j] + spread[j]
                    hit_sl = ask_h >= pos.sl
                    hit_tp = ask_l <= pos.tp
                    if hit_sl:
                        close(pos, max(ask_o, pos.sl), times[j], "sl" if pos.sl > pos.entry else "be")
                        pos = None
                    elif hit_tp:
                        close(pos, min(ask_o, pos.tp), times[j], "tp")
                        pos = None
                # breakeven after bar close
                if pos is not None and risk.breakeven_at_r:
                    trigger = risk.breakeven_at_r * pos.risk_dist
                    if pos.side > 0 and pos.sl < pos.entry and h[j] - pos.entry >= trigger:
                        pos.sl = pos.entry
                    elif pos.side < 0 and pos.sl > pos.entry and pos.entry - (lo[j] + spread[j]) >= trigger:
                        pos.sl = pos.entry

        # 3) new signal on this bar's close -> pending for next bar
        if sig[j] != 0 and j + 1 < n:
            guard = check_guards(
                GuardState(
                    equity=balance, day_start_equity=day_start_bal, trades_today=trades_today,
                    open_positions=1 if pos is not None else 0, spread=float(spread[j]), hour_utc=int(hours[j]),
                ),
                risk,
            )
            if guard is None:
                pending = j
            else:
                key = guard.split(" (")[0]
                skipped[key] = skipped.get(key, 0) + 1

        # 4) mark to market at the worst price this bar traded through
        equity_rows.append((times[j], balance, balance + _floating(pos, lo[j], h[j], spread[j], spec, bt)))

    if pos is not None and n:  # mark-to-market at last close
        last = data["close"].iloc[-1]
        close(pos, last if pos.side > 0 else last + spread[-1], times[-1], "end_of_data")
        pos = None
        equity_rows[-1] = (times[-1], balance, balance)

    trades_df = pd.DataFrame([asdict(t) for t in trades])
    equity_df = pd.DataFrame(equity_rows, columns=["time_utc", "balance", "equity"])
    stats = compute_stats(trades_df, equity_df, bt.initial_balance)
    stats["spread_model"] = spread_info
    stats["signals_skipped"] = skipped
    return BacktestResult(trades=trades_df, equity=equity_df, stats=stats)


def _floating(pos: Optional[Trade], low: float, high: float, spread: float, spec: SymbolSpec, bt: BacktestConfig) -> float:
    """Unrealised PnL of `pos` at the worst price inside this bar (0 when flat)."""
    if pos is None:
        return 0.0
    adverse = low if pos.side > 0 else high + spread  # longs mark on bid, shorts on ask
    gross = (adverse - pos.entry) * pos.side * pos.lots * spec.contract_size
    return gross - bt.commission_per_lot * pos.lots  # the exit cost is already owed


def compute_stats(trades: pd.DataFrame, equity: pd.DataFrame, initial: float) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    gross_win, gross_loss = wins.pnl.sum(), -losses.pnl.sum()
    bal = equity["balance"].to_numpy()
    final = float(bal[-1])
    return {
        "trades": int(len(trades)),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "net_profit": round(final - initial, 2),
        "return_pct": round((final / initial - 1) * 100, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "expectancy_r": round(float(trades.r_multiple.mean()), 3),
        "avg_win_r": round(float(wins.r_multiple.mean()), 3) if len(wins) else 0.0,
        "avg_loss_r": round(float(losses.r_multiple.mean()), 3) if len(losses) else 0.0,
        # marked to market every bar — this is the drawdown an open position put you through
        "max_drawdown_pct": round(_max_drawdown(equity["equity"].to_numpy()) * 100, 2),
        # realised only, i.e. the old closed-trade measure; always <= the one above
        "max_drawdown_closed_pct": round(_max_drawdown(bal) * 100, 2),
        "max_consecutive_losses": int(_max_streak(trades.pnl.to_numpy() <= 0)),
        "exit_reasons": trades.exit_reason.value_counts().to_dict(),
        "final_balance": round(final, 2),
    }


def _max_drawdown(series: np.ndarray) -> float:
    if len(series) == 0:
        return 0.0
    peak = np.maximum.accumulate(series)
    dd = np.where(peak > 0, (peak - series) / np.where(peak > 0, peak, 1.0), 1.0)
    return float(dd.max())


def _max_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best
