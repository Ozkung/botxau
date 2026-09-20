"""Broker abstraction used by the live engine (MT5 today; others later)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..risk import SymbolSpec


@dataclass(frozen=True)
class Tick:
    bid: float
    ask: float
    time_server: pd.Timestamp

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class Position:
    ticket: int
    side: int            # +1 long / -1 short
    lots: float
    price_open: float
    sl: float
    tp: float
    time_server: pd.Timestamp
    comment: str = ""


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    ticket: Optional[int]
    price: Optional[float]
    message: str


class Broker(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...

    @abstractmethod
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...

    @abstractmethod
    def closed_bars(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame:
        """Last ``count`` CLOSED bars: columns time (server), open, high, low, close."""

    @abstractmethod
    def tick(self, symbol: str) -> Tick: ...

    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def server_utc_offset_hours(self, symbol: str) -> int: ...

    @abstractmethod
    def positions(self, symbol: str, magic: int) -> list[Position]: ...

    @abstractmethod
    def market_order(self, symbol: str, side: int, lots: float, sl: float, tp: float,
                     magic: int, comment: str) -> OrderResult: ...

    @abstractmethod
    def modify_sltp(self, symbol: str, ticket: int, sl: float, tp: float) -> OrderResult: ...

    @abstractmethod
    def close_position(self, symbol: str, position: Position, magic: int) -> OrderResult: ...
