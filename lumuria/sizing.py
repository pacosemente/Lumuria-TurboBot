"""Position sizing: how much USD to deploy on each entry.

All sizers are pure functions of the current bankroll and the current win
streak, so they're trivial to test and compare. The live trader caps every
result at the available bankroll.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class PositionSizer(ABC):
    name: str = "base"

    @abstractmethod
    def size(self, bankroll: float, wins_streak: int) -> float:
        raise NotImplementedError


class FixedSizer(PositionSizer):
    """Same amount every time."""

    def __init__(self, amount: float = 25.0) -> None:
        self.amount = amount
        self.name = f"fixed(${amount:,.0f})"

    def size(self, bankroll: float, wins_streak: int) -> float:
        return self.amount


class BankrollFractionSizer(PositionSizer):
    """A fixed fraction of the *current* bankroll, so it compounds as you win
    and shrinks as you lose. Start small, grow with the account."""

    def __init__(self, fraction: float = 0.05, min_usd: float = 5.0) -> None:
        self.fraction = fraction
        self.min_usd = min_usd
        self.name = f"bankroll({fraction:.0%}, min ${min_usd:,.0f})"

    def size(self, bankroll: float, wins_streak: int) -> float:
        return max(self.min_usd, bankroll * self.fraction)


class RampUpSizer(PositionSizer):
    """Start with a small base and scale up after each consecutive win, up to a
    cap; reset to base after a loss. Directly encodes "começar com pouco e ir
    crescendo" while a fresh token (no streak) is always probed small."""

    def __init__(self, base: float = 10.0, step: float = 1.6,
                 cap: float | None = None) -> None:
        self.base = base
        self.step = step
        self.cap = cap if cap is not None else base * 10
        self.name = f"rampup(base ${base:,.0f}, x{step}, cap ${self.cap:,.0f})"

    def size(self, bankroll: float, wins_streak: int) -> float:
        return min(self.base * (self.step ** max(0, wins_streak)), self.cap)
