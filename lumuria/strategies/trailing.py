from __future__ import annotations

from ..models import Position, SellOrder
from .base import ExitStrategy


class TrailingStop(ExitStrategy):
    """Hard stop while underwater, then trail the peak to let winners run.

    The trailing stop only arms once price has risen `arm_pct` above entry, so
    early chop near the entry doesn't shake us out before the move happens.
    """

    def __init__(
        self,
        hard_stop_pct: float = 0.30,
        arm_pct: float = 0.20,
        trail_pct: float = 0.35,
    ) -> None:
        self.hard_stop_pct = hard_stop_pct
        self.arm_pct = arm_pct
        self.trail_pct = trail_pct
        self.name = f"trailing(stop -{hard_stop_pct:.0%}, trail {trail_pct:.0%})"

    @property
    def initial_risk_pct(self) -> float:
        return self.hard_stop_pct

    def on_tick(self, position: Position, price: float) -> list[SellOrder]:
        position.peak_price = max(position.peak_price, price)
        armed = position.peak_price >= position.entry_price * (1 + self.arm_pct)

        if armed:
            if price <= position.peak_price * (1 - self.trail_pct):
                return [SellOrder(1.0, "trail")]
        elif price <= position.entry_price * (1 - self.hard_stop_pct):
            return [SellOrder(1.0, "stop")]
        return []
