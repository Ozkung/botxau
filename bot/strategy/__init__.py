"""Strategy registry — add new strategies here."""
from __future__ import annotations

from .base import Signal, Strategy
from .session_breakout import SessionBreakout

REGISTRY: dict[str, type[Strategy]] = {
    SessionBreakout.name: SessionBreakout,
}


def create_strategy(name: str, params: dict | None = None) -> Strategy:
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown strategy '{name}'. Available: {sorted(REGISTRY)}") from None
    return cls(**(params or {}))


__all__ = ["Signal", "Strategy", "SessionBreakout", "REGISTRY", "create_strategy"]
