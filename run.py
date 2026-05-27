#!/usr/bin/env python3
"""Run the paper-trading sniper simulation and compare exit strategies.

Everything is simulated: no keys, no funds, no network. Example:

    python3 run.py --tokens 1000 --seed 7 --position-usd 100
"""
from __future__ import annotations

import argparse

from lumuria import metrics
from lumuria.engine import Backtest
from lumuria.execution import PaperBroker
from lumuria.feeds import SimulatedFeed
from lumuria.models import BacktestResult
from lumuria.safety import SafetyConfig, SafetyFilter
from lumuria.strategies import FixedStopTarget, ScaledExit, TrailingStop


def build_strategies():
    return {
        "Fixed stop/target": lambda: FixedStopTarget(stop_pct=0.30, target_pct=1.00),
        "Trailing stop": lambda: TrailingStop(
            hard_stop_pct=0.30, arm_pct=0.20, trail_pct=0.35
        ),
        "Scaled exit": lambda: ScaledExit(
            stop_pct=0.30, first_target_pct=0.50, first_fraction=0.50, trail_pct=0.35
        ),
    }


def print_report(label: str, result: BacktestResult, position_usd: float) -> None:
    m = metrics.compute(result.trades)
    print(f"\n  {label}")
    print(f"    strategy        : {result.strategy}")
    print(f"    trades taken    : {m.trades}")
    print(f"    win rate        : {m.win_rate:.1%}  ({m.wins}W / {m.losses}L)")
    print(f"    avg win / loss  : ${m.avg_win_usd:+,.2f} / ${m.avg_loss_usd:+,.2f}")
    print(f"    expectancy      : ${m.expectancy_usd:+,.2f} per trade  "
          f"({m.expectancy_r:+.2f} R)")
    print(f"    profit factor   : {m.profit_factor:.2f}")
    print(f"    total P&L       : ${m.total_pnl_usd:+,.2f}  "
          f"(on ${position_usd:,.0f}/trade)")
    print(f"    max drawdown    : ${m.max_drawdown_usd:,.2f}")
    print(f"    best / worst    : {m.best_r:+.1f} R / {m.worst_r:+.1f} R")
    verdict = "PROFITABLE (positive expectancy)" if m.is_profitable() \
        else "unprofitable (negative expectancy)"
    print(f"    verdict         : {verdict}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokens", type=int, default=1000,
                        help="number of token launches to simulate")
    parser.add_argument("--seed", type=int, default=42,
                        help="RNG seed (same seed -> same market for all strategies)")
    parser.add_argument("--position-usd", type=float, default=100.0,
                        help="USD deployed per sniped token")
    parser.add_argument("--fee-pct", type=float, default=0.01)
    parser.add_argument("--slippage-pct", type=float, default=0.02)
    parser.add_argument("--min-liquidity", type=float, default=8_000.0)
    parser.add_argument("--cruel", action="store_true",
                        help="brutal-but-honest DeFi reality: more scams, stops "
                             "that gap through, worse exit fills, priority fees")
    args = parser.parse_args()

    launches = SimulatedFeed(n=args.tokens, seed=args.seed,
                             cruel=args.cruel).materialize()
    safety = SafetyFilter(SafetyConfig(min_liquidity_usd=args.min_liquidity))
    if args.cruel:
        broker = PaperBroker(fee_pct=0.015, slippage_pct=0.06,
                             exit_slippage_pct=0.12,
                             priority_fee_usd=max(0.5, args.position_usd * 0.01))
    else:
        broker = PaperBroker(fee_pct=args.fee_pct, slippage_pct=args.slippage_pct)
    engine = Backtest(safety=safety, broker=broker, position_usd=args.position_usd)

    taken_example = engine.run(launches, list(build_strategies().values())[0])

    mode = "CRUEL (realistic DeFi)" if args.cruel else "baseline"
    print("=" * 64)
    print(f"  LUMURIA TURBOBOT — paper-trading sniper simulation  [{mode}]")
    print("=" * 64)
    print(f"  launches simulated : {len(launches)}")
    print(f"  rejected by safety : {taken_example.skipped} "
          f"(of those, {taken_example.skipped_saved} were rug/honeypot — losses dodged)")
    print(f"  sniped (per strat) : {len(taken_example.trades)}")
    print(f"  position size      : ${args.position_usd:,.0f}  |  "
          f"fee {args.fee_pct:.1%}  |  slippage {args.slippage_pct:.1%}")

    for label, factory in build_strategies().items():
        print_report(label, engine.run(launches, factory), args.position_usd)

    print("\n" + "=" * 64)
    print("  Reminder: simulated data. Real markets add MEV, failed txns,")
    print("  changing liquidity and worse fills. Treat this as a lab, not a")
    print("  promise. Tune assumptions in feeds/simulated.py.")
    print("=" * 64)


if __name__ == "__main__":
    main()
