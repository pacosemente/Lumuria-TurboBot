"""Exit strategy interface.

A strategy never decides *what* to buy (the feed + safety filter do that).
It only decides when and how much to sell, tick by tick.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Position, SellOrder


class ExitStrategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def initial_risk_pct(self) -> float:
        """Stop distance that defines one unit of risk (1R) for this strategy."""
        raise NotImplementedError

    @abstractmethod
    def on_tick(self, position: Position, price: float) -> list[SellOrder]:
        """Return sell orders (fractions of current holding) for this tick."""
        raise NotImplementedError
