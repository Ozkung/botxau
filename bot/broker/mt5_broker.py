"""MetaTrader 5 adapter (official ``MetaTrader5`` Python package — Windows only).

The MT5 terminal must be installed, running and logged in (or credentials
given in config), with "Algo Trading" enabled.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd

from ..config import MT5Config
from ..risk import SymbolSpec
from .base import Broker, OrderResult, Position, Tick

log = logging.getLogger(__name__)

try:  # imported lazily so backtests/tests run on macOS/Linux
    import MetaTrader5 as mt5  # type: ignore
except ImportError:  # pragma: no cover
    mt5 = None


def _tf(name: str) -> int:
    mapping = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    return mapping[name.upper()]


class MT5Broker(Broker):
    DEVIATION_POINTS = 30  # max slippage accepted on market orders

    def __init__(self, cfg: MT5Config, fallback_utc_offset: Optional[int] = None):
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package not available — install it on Windows: pip install MetaTrader5")
        self.cfg = cfg
        self.fallback_utc_offset = fallback_utc_offset
        self._offset_cache: Optional[int] = None

    # --- lifecycle -------------------------------------------------------
    def connect(self) -> None:
        kwargs = {}
        if self.cfg.path:
            kwargs["path"] = self.cfg.path
        if self.cfg.login:
            kwargs.update(login=int(self.cfg.login), password=self.cfg.password, server=self.cfg.server)
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
        info = mt5.account_info()
        term = mt5.terminal_info()
        log.info("MT5 connected: login=%s server=%s balance=%.2f %s trade_allowed=%s",
                 info.login, info.server, info.balance, info.currency, term.trade_allowed)
        if not term.trade_allowed:
            log.warning("Algo Trading is DISABLED in the terminal — orders will be rejected")

    def shutdown(self) -> None:
        mt5.shutdown()

    # --- market data -----------------------------------------------------
    def symbol_spec(self, symbol: str) -> SymbolSpec:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Symbol {symbol} not available: {mt5.last_error()}")
        s = mt5.symbol_info(symbol)
        return SymbolSpec(
            contract_size=s.trade_contract_size,
            volume_min=s.volume_min,
            volume_step=s.volume_step,
            volume_max=s.volume_max,
            digits=s.digits,
            stops_level=s.trade_stops_level * s.point,
        )

    def closed_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, _tf(timeframe), 1, count)  # pos 1 = skip forming bar
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"copy_rates_from_pos failed: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")  # server time, naive
        return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

    def tick(self, symbol: str) -> Tick:
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            raise RuntimeError(f"No tick for {symbol}: {mt5.last_error()}")
        return Tick(bid=t.bid, ask=t.ask, time_server=pd.to_datetime(t.time, unit="s"))

    def equity(self) -> float:
        return float(mt5.account_info().equity)

    def server_utc_offset_hours(self, symbol: str) -> int:
        """Server time - UTC, estimated from the latest tick (handles DST shifts).

        Only trustworthy while the market is live; falls back to the config value.
        """
        t = mt5.symbol_info_tick(symbol)
        now = time.time()
        if t is not None and abs(t.time - now) < 12 * 3600 + 600:
            diff_h = round((t.time - now) / 3600)
            # tick.time lags slightly; rounding to hours absorbs that
            if self._offset_cache != diff_h:
                log.info("Server UTC offset detected: %+d h", diff_h)
            self._offset_cache = diff_h
            return diff_h
        if self._offset_cache is not None:
            return self._offset_cache
        if self.fallback_utc_offset is None:
            raise RuntimeError("Cannot detect server UTC offset — set server_utc_offset in config")
        return self.fallback_utc_offset

    # --- trading ---------------------------------------------------------
    def positions(self, symbol: str, magic: int) -> list[Position]:
        raw = mt5.positions_get(symbol=symbol) or ()
        out = []
        for p in raw:
            if p.magic != magic:
                continue
            out.append(Position(
                ticket=p.ticket, side=1 if p.type == mt5.POSITION_TYPE_BUY else -1,
                lots=p.volume, price_open=p.price_open, sl=p.sl, tp=p.tp,
                time_server=pd.to_datetime(p.time, unit="s"), comment=p.comment,
            ))
        return out

    def _filling(self, symbol: str) -> int:
        mode = mt5.symbol_info(symbol).filling_mode
        if mode & 1:   # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        if mode & 2:   # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _send(self, request: dict) -> OrderResult:
        res = mt5.order_send(request)
        if res is None:
            return OrderResult(False, None, None, f"order_send returned None: {mt5.last_error()}")
        ok = res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
        ticket = getattr(res, "order", None) or getattr(res, "deal", None)
        return OrderResult(ok, ticket, getattr(res, "price", None), f"retcode={res.retcode} {res.comment}")

    def market_order(self, symbol, side, lots, sl, tp, magic, comment) -> OrderResult:
        tick = mt5.symbol_info_tick(symbol)
        digits = mt5.symbol_info(symbol).digits
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if side > 0 else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if side > 0 else tick.bid,
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": self.DEVIATION_POINTS,
            "magic": magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(symbol),
        }
        return self._send(req)

    def modify_sltp(self, symbol, ticket, sl, tp) -> OrderResult:
        digits = mt5.symbol_info(symbol).digits
        return self._send({
            "action": mt5.TRADE_ACTION_SLTP, "symbol": symbol, "position": ticket,
            "sl": round(sl, digits), "tp": round(tp, digits),
        })

    def close_position(self, symbol, position: Position, magic: int) -> OrderResult:
        tick = mt5.symbol_info_tick(symbol)
        return self._send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "position": position.ticket,
            "volume": position.lots,
            "type": mt5.ORDER_TYPE_SELL if position.side > 0 else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if position.side > 0 else tick.ask,
            "deviation": self.DEVIATION_POINTS, "magic": magic, "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(symbol),
        })
