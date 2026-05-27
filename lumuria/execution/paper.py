"""Paper broker: simulates fills with fees and slippage. No real orders."""
from __future__ import annotations

from ..models import Position, TokenLaunch


class PaperBroker:
    def __init__(self, fee_pct: float = 0.01, slippage_pct: float = 0.02) -> None:
        self.fee_pct = fee_pct          # swap fee + priority fee, as a fraction
        self.slippage_pct = slippage_pct  # adverse price impact on each fill

    def buy(
        self, launch: TokenLaunch, usd: float, initial_risk_pct: float
    ) -> Position:
        return self.buy_at_price(launch.snapshot.symbol, launch.path[0].price,
                                 usd, initial_risk_pct)

    def buy_at_price(
        self, symbol: str, price: float, usd: float, initial_risk_pct: float
    ) -> Position:
        fill_price = price * (1 + self.slippage_pct)
        usd_after_fee = usd * (1 - self.fee_pct)
        tokens = usd_after_fee / fill_price
        return Position(
            symbol=symbol,
            entry_price=fill_price,
            tokens=tokens,
            cost_usd=usd,
            initial_tokens=tokens,
            initial_risk_pct=initial_risk_pct,
        )

    def sell(self, position: Position, price: float, fraction: float) -> float:
        """Sell a fraction of the current holding. Returns USD proceeds."""
        fraction = max(0.0, min(1.0, fraction))
        tokens_sold = position.tokens * fraction
        fill_price = price * (1 - self.slippage_pct)
        proceeds = tokens_sold * fill_price * (1 - self.fee_pct)
        position.tokens -= tokens_sold
        return proceeds
