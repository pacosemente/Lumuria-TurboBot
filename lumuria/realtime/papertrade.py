"""Live paper trader: real prices in, simulated fills, no real money out.

Opens a paper position when the scanner says ENTER, then is fed real price
updates each scan cycle. It reuses the same ExitStrategy objects as the
backtest, so a strategy behaves identically live and in simulation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..execution import PaperBroker
from ..metrics import Metrics, compute
from ..models import Trade
from ..models import Fate
from ..strategies.base import ExitStrategy

StrategyFactory = Callable[[], ExitStrategy]


@dataclass
class _Open:
    symbol: str
    strategy: ExitStrategy
    entry_price: float
    cost_usd: float
    initial_risk_pct: float
    tokens: float
    initial_tokens: float
    peak_price: float
    proceeds: float = 0.0
    sold_tokens: float = 0.0
    weighted_exit: float = 0.0


@dataclass
class LivePaperTrader:
    broker: PaperBroker
    strategy_factory: StrategyFactory
    sizer: "PositionSizer"  # noqa: F821 (typing only)
    starting_bankroll: float = 500.0
    min_position_usd: float = 2.0

    bankroll: float = field(init=False)
    wins_streak: int = field(init=False, default=0)
    open: dict[str, _Open] = field(init=False, default_factory=dict)
    trades: list[Trade] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.bankroll = self.starting_bankroll

    @property
    def equity_open_cost(self) -> float:
        return sum(o.cost_usd for o in self.open.values())

    def can_open(self, mint: str, price: float | None) -> bool:
        return (mint not in self.open and price is not None and price > 0
                and self.bankroll >= self.min_position_usd)

    def open_position(self, mint: str, symbol: str, price: float) -> float | None:
        if not self.can_open(mint, price):
            return None
        size = min(self.sizer.size(self.bankroll, self.wins_streak), self.bankroll)
        if size < self.min_position_usd:
            return None
        strat = self.strategy_factory()
        pos = self.broker.buy_at_price(symbol, price, size, strat.initial_risk_pct)
        self.bankroll -= size
        self.open[mint] = _Open(
            symbol=symbol, strategy=strat, entry_price=pos.entry_price,
            cost_usd=pos.cost_usd, initial_risk_pct=pos.initial_risk_pct,
            tokens=pos.tokens, initial_tokens=pos.initial_tokens,
            peak_price=pos.entry_price,
        )
        return size

    def tick(self, mint: str, price: float) -> Trade | None:
        o = self.open.get(mint)
        if o is None or price <= 0:
            return None
        o.peak_price = max(o.peak_price, price)
        # The ExitStrategy works on a Position; bridge our _Open to it.
        pos = _as_position(o)
        for order in o.strategy.on_tick(pos, price):
            before = pos.tokens
            proceeds = self.broker.sell(pos, price, order.fraction)
            sold = before - pos.tokens
            o.proceeds += proceeds
            o.sold_tokens += sold
            o.weighted_exit += sold * price
            self.bankroll += proceeds
        o.tokens = pos.tokens
        o.peak_price = pos.peak_price
        if o.tokens <= 1e-12:
            return self._finalize(mint, price, reason="exit")
        return None

    def force_close(self, mint: str, price: float, reason: str = "session-end") -> Trade | None:
        o = self.open.get(mint)
        if o is None:
            return None
        if price > 0 and o.tokens > 1e-12:
            pos = _as_position(o)
            before = pos.tokens
            proceeds = self.broker.sell(pos, price, 1.0)
            o.proceeds += proceeds
            o.sold_tokens += before - pos.tokens
            o.weighted_exit += (before - pos.tokens) * price
            self.bankroll += proceeds
            o.tokens = pos.tokens
        return self._finalize(mint, price, reason=reason)

    def _finalize(self, mint: str, last_price: float, *, reason: str) -> Trade:
        o = self.open.pop(mint)
        avg_exit = o.weighted_exit / o.sold_tokens if o.sold_tokens else last_price
        pnl = o.proceeds - o.cost_usd
        risk = o.cost_usd * o.initial_risk_pct
        trade = Trade(
            symbol=o.symbol, strategy=o.strategy.name, fate=Fate.FLAT,
            entry_price=o.entry_price, exit_price=avg_exit,
            pnl_usd=pnl, pnl_r=(pnl / risk if risk else 0.0), reason=reason,
        )
        self.trades.append(trade)
        self.wins_streak = self.wins_streak + 1 if pnl > 0 else 0
        return trade

    def metrics(self) -> Metrics:
        return compute(self.trades)

    @property
    def roi_pct(self) -> float:
        return (self.bankroll + self.equity_open_cost - self.starting_bankroll) \
            / self.starting_bankroll if self.starting_bankroll else 0.0


def _as_position(o: _Open):
    from ..models import Position
    p = Position(
        symbol=o.symbol, entry_price=o.entry_price, tokens=o.tokens,
        cost_usd=o.cost_usd, initial_tokens=o.initial_tokens,
        initial_risk_pct=o.initial_risk_pct, peak_price=o.peak_price,
    )
    return p
