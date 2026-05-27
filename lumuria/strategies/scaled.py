from __future__ import annotations

from ..models import Position, SellOrder
from .base import ExitStrategy


class ScaledExit(ExitStrategy):
    """Take partial profit early, then trail the rest to catch moonshots.

    Sell `first_fraction` of the bag at +`first_target_pct` (de-risking the
    trade), then trail the remainder. A hard stop protects the whole position
    until the first target is hit.
    """

    def __init__(
        self,
        stop_pct: float = 0.30,
        first_target_pct: float = 0.50,
        first_fraction: float = 0.50,
        trail_pct: float = 0.35,
    ) -> None:
        self.stop_pct = stop_pct
        self.first_target_pct = first_target_pct
        self.first_fraction = first_fraction
        self.trail_pct = trail_pct
        self._took_first = False
        self.name = (
            f"scaled(stop -{stop_pct:.0%}, take {first_fraction:.0%}"
            f"@+{first_target_pct:.0%}, trail {trail_pct:.0%})"
        )

    @property
    def initial_risk_pct(self) -> float:
        return self.stop_pct

    def reset(self) -> None:
        self._took_first = False

    def on_tick(self, position: Position, price: float) -> list[SellOrder]:
        position.peak_price = max(position.peak_price, price)

        if not self._took_first:
            if price <= position.entry_price * (1 - self.stop_pct):
                return [SellOrder(1.0, "stop")]
            if price >= position.entry_price * (1 + self.first_target_pct):
                self._took_first = True
                return [SellOrder(self.first_fraction, "scale-out")]
            return []

        # Remainder rides a trailing stop.
        if price <= position.peak_price * (1 - self.trail_pct):
            return [SellOrder(1.0, "trail")]
        return []
