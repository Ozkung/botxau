"""Bar-by-bar backtester.

Execution model (deliberately conservative):
* Bars are BID prices. Longs enter at ask (= open + spread), exit at bid.
  Shorts enter at bid, exit at ask (= price + spread).
* Signal on bar i's close -> market entry at bar i+1's open.
* SL/TP checked on bar high/low. If both are touched in the same bar, SL wins.
* Gaps through SL/TP fill at the bar open (slippage in your disfavour for SL).
* Breakeven is applied at the end of a bar (cannot help within the same bar).
* Force-close at the open of the first bar whose UTC hour >= force_close_utc.
* Daily loss guard uses realised balance vs balance at UTC-day start.
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


def run_backtest(df: pd.DataFrame, strategy: Strategy, risk: RiskConfig, bt: BacktestConfig) -> BacktestResult:
    data = strategy.prepare(df)
    n = len(data)
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

    spec = SymbolSpec(
        contract_size=bt.contract_size,
        volume_min=bt.volume_min,
        volume_step=bt.volume_step,
        volume_max=bt.volume_max,
    )
    spread = bt.spread
    balance = bt.initial_balance
    equity_rows = [(times[0] if n else None, balance)]
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
        trade.r_multiple = gross / (trade.risk_dist * trade.lots * spec.contract_size)
        balance += trade.pnl
        trades.append(trade)
        equity_rows.append((when, balance))

    for j in range(strategy.min_bars, n):
        if days[j] != cur_day:
            cur_day, day_start_bal, trades_today = days[j], balance, 0

        # 1) execute pending entry at this bar's open
        if pending is not None and pos is None:
            i = pending
            side = int(sig[i])
            entry = o[j] + spread if side > 0 else o[j]
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
                px = o[j] if pos.side > 0 else o[j] + spread
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
                    ask_h, ask_l, ask_o = h[j] + spread, lo[j] + spread, o[j] + spread
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
                    elif pos.side < 0 and pos.sl > pos.entry and pos.entry - (lo[j] + spread) >= trigger:
                        pos.sl = pos.entry

        # 3) new signal on this bar's close -> pending for next bar
        if sig[j] != 0 and j + 1 < n:
            guard = check_guards(
                GuardState(
                    equity=balance, day_start_equity=day_start_bal, trades_today=trades_today,
                    open_positions=1 if pos is not None else 0, spread=spread, hour_utc=int(hours[j]),
                ),
                risk,
            )
            if guard is None:
                pending = j
            else:
                key = guard.split(" (")[0]
                skipped[key] = skipped.get(key, 0) + 1

    if pos is not None and n:  # mark-to-market at last close
        last = data["close"].iloc[-1]
        close(pos, last if pos.side > 0 else last + spread, times[-1], "end_of_data")

    trades_df = pd.DataFrame([asdict(t) for t in trades])
    equity_df = pd.DataFrame(equity_rows, columns=["time_utc", "balance"])
    stats = compute_stats(trades_df, equity_df, bt.initial_balance)
    stats["signals_skipped"] = skipped
    return BacktestResult(trades=trades_df, equity=equity_df, stats=stats)


def compute_stats(trades: pd.DataFrame, equity: pd.DataFrame, initial: float) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins = trades[trades.pnl > 0]
    losses = trades[trades.pnl <= 0]
    gross_win, gross_loss = wins.pnl.sum(), -losses.pnl.sum()
    bal = equity["balance"].to_numpy()
    peak = np.maximum.accumulate(bal)
    dd = (peak - bal) / peak
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
        "max_drawdown_pct": round(float(dd.max()) * 100, 2),
        "max_consecutive_losses": int(_max_streak(trades.pnl.to_numpy() <= 0)),
        "exit_reasons": trades.exit_reason.value_counts().to_dict(),
        "final_balance": round(final, 2),
    }


def _max_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best
