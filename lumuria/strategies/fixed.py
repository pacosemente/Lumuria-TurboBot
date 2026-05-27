from __future__ import annotations

from ..models import Position, SellOrder
from .base import ExitStrategy


class FixedStopTarget(ExitStrategy):
    """Sell everything at a fixed stop-loss or a fixed take-profit target."""

    def __init__(self, stop_pct: float = 0.30, target_pct: float = 1.00) -> None:
        self.stop_pct = stop_pct
        self.target_pct = target_pct
        self.name = f"fixed(stop -{stop_pct:.0%}, target +{target_pct:.0%})"

    @property
    def initial_risk_pct(self) -> float:
        return self.stop_pct

    def on_tick(self, position: Position, price: float) -> list[SellOrder]:
        if price <= position.entry_price * (1 - self.stop_pct):
            return [SellOrder(1.0, "stop")]
        if price >= position.entry_price * (1 + self.target_pct):
            return [SellOrder(1.0, "target")]
        return []
