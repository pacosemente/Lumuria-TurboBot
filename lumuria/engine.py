"""Backtest engine: feed -> safety filter -> paper broker -> exit strategy."""
from __future__ import annotations

from typing import Callable

from .execution import PaperBroker
from .feeds.base import PairFeed
from .models import BacktestResult, Fate, Position, TokenLaunch, Trade
from .safety import SafetyFilter
from .strategies.base import ExitStrategy

StrategyFactory = Callable[[], ExitStrategy]


class Backtest:
    def __init__(
        self,
        safety: SafetyFilter,
        broker: PaperBroker,
        position_usd: float = 100.0,
    ) -> None:
        self.safety = safety
        self.broker = broker
        self.position_usd = position_usd

    def run(
        self,
        launches: list[TokenLaunch] | PairFeed,
        strategy_factory: StrategyFactory,
    ) -> BacktestResult:
        if isinstance(launches, PairFeed):
            launches = list(launches.stream())

        result = BacktestResult(strategy=strategy_factory().name)

        for launch in launches:
            passed, _ = self.safety.evaluate(launch.snapshot)
            if not passed:
                result.skipped += 1
                if launch.fate in (Fate.RUG, Fate.HONEYPOT):
                    result.skipped_saved += 1
                continue

            trade = self._trade_one(launch, strategy_factory())
            result.trades.append(trade)

        return result

    def _trade_one(self, launch: TokenLaunch, strategy: ExitStrategy) -> Trade:
        position = self.broker.buy(
            launch, self.position_usd, strategy.initial_risk_pct
        )
        can_sell = launch.fate is not Fate.HONEYPOT  # honeypots trap the buyer

        proceeds = 0.0
        sold_tokens = 0.0
        weighted_exit = 0.0
        last_reason = "end"
        last_price = position.entry_price

        for tick in launch.path[1:]:
            last_price = tick.price
            if not can_sell:
                continue
            for order in strategy.on_tick(position, tick.price):
                before = position.tokens
                proceeds += self.broker.sell(position, tick.price, order.fraction)
                sold = before - position.tokens
                sold_tokens += sold
                weighted_exit += sold * tick.price
                last_reason = order.reason
            if position.tokens <= 1e-12:
                break

        # Force-close any remainder at the final price (token's life ended).
        if position.tokens > 1e-12:
            if can_sell:
                before = position.tokens
                proceeds += self.broker.sell(position, last_price, 1.0)
                sold = before - position.tokens
                sold_tokens += sold
                weighted_exit += sold * last_price
            else:
                sold_tokens += position.tokens
                position.tokens = 0.0  # honeypot: bag is worthless

        avg_exit = weighted_exit / sold_tokens if sold_tokens else last_price
        pnl_usd = proceeds - position.cost_usd
        risk_usd = self.position_usd * strategy.initial_risk_pct
        pnl_r = pnl_usd / risk_usd if risk_usd else 0.0

        return Trade(
            symbol=launch.snapshot.symbol,
            strategy=strategy.name,
            fate=launch.fate,
            entry_price=position.entry_price,
            exit_price=avg_exit,
            pnl_usd=pnl_usd,
            pnl_r=pnl_r,
            reason="honeypot" if not can_sell else last_reason,
        )
