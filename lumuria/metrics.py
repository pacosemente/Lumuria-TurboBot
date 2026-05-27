"""Turn a list of closed trades into the numbers that actually matter."""
from __future__ import annotations

from dataclasses import dataclass

from .models import Trade


@dataclass
class Metrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_usd: float
    avg_loss_usd: float
    expectancy_usd: float   # expected profit per trade
    expectancy_r: float     # expected profit per trade, in R units
    profit_factor: float    # gross profit / gross loss
    total_pnl_usd: float
    max_drawdown_usd: float
    best_r: float
    worst_r: float

    def is_profitable(self) -> bool:
        return self.expectancy_usd > 0


def compute(trades: list[Trade]) -> Metrics:
    n = len(trades)
    if n == 0:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss = -sum(t.pnl_usd for t in losses)  # positive magnitude

    total_pnl = sum(t.pnl_usd for t in trades)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = -gross_loss / len(losses) if losses else 0.0  # negative
    expectancy_usd = total_pnl / n
    expectancy_r = sum(t.pnl_r for t in trades) / n
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0
        else float("inf") if gross_profit > 0 else 0.0
    )

    # Max drawdown on the sequential equity curve.
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.pnl_usd
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return Metrics(
        trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=len(wins) / n,
        avg_win_usd=avg_win,
        avg_loss_usd=avg_loss,
        expectancy_usd=expectancy_usd,
        expectancy_r=expectancy_r,
        profit_factor=profit_factor,
        total_pnl_usd=total_pnl,
        max_drawdown_usd=max_dd,
        best_r=max((t.pnl_r for t in trades), default=0.0),
        worst_r=min((t.pnl_r for t in trades), default=0.0),
    )
