#!/usr/bin/env python3
"""Project 1 SOL through the CRUEL market using the winning setup
(selective entries + trailing stop), compounding over time.

Reports a RANGE across seeds — best, typical and worst — because memecoin
sniping is wildly high-variance: the average hides runs that moon and runs
that bleed. Offline, no network. Illustrative, not a promise.

    python3 projection.py --start-sol 1 --days 30 --per-day 25
"""
from __future__ import annotations

import argparse
from statistics import median

from lumuria.execution import PaperBroker
from lumuria.feeds import SimulatedFeed
from lumuria.models import Fate
from lumuria.safety import SafetyConfig, SafetyFilter
from lumuria.strategies import TrailingStop


def simulate_trade(launch, strategy, broker, size_sol: float) -> float:
    pos = broker.buy_at_price(launch.snapshot.symbol, launch.path[0].price,
                              size_sol, strategy.initial_risk_pct)
    can_sell = launch.fate is not Fate.HONEYPOT
    proceeds, last = 0.0, pos.entry_price
    for tick in launch.path[1:]:
        last = tick.price
        if not can_sell:
            continue
        for order in strategy.on_tick(pos, tick.price):
            proceeds += broker.sell(pos, tick.price, order.fraction)
        if pos.tokens <= 1e-12:
            break
    if pos.tokens > 1e-12:
        if can_sell:
            proceeds += broker.sell(pos, last, 1.0)
        else:
            pos.tokens = 0.0
    return proceeds - pos.cost_usd  # pnl in SOL


def passing_launches(seed: int, need: int, min_liq: float) -> list:
    safety = SafetyFilter(SafetyConfig(min_liquidity_usd=min_liq))
    out, n = [], max(need * 12, 3000)
    for launch in SimulatedFeed(n=n, seed=seed, cruel=True).stream():
        if safety.evaluate(launch.snapshot)[0]:
            out.append(launch)
            if len(out) >= need:
                break
    return out


def run_one(seed, trades, min_liq, start_sol, risk, max_pos, trail) -> dict:
    broker = PaperBroker(fee_pct=0.015, slippage_pct=0.06, exit_slippage_pct=0.12,
                         priority_fee_usd=0.0005)  # ~priority fee in SOL terms
    launches = passing_launches(seed, trades, min_liq)
    bankroll = start_sol
    peak, max_dd = start_sol, 0.0
    wins = 0
    for launch in launches:
        size = min(bankroll * risk, max_pos, bankroll)
        if size <= 0:
            break
        pnl = simulate_trade(launch, TrailingStop(0.30, 0.20, trail), broker, size)
        bankroll += pnl
        wins += pnl > 0
        peak = max(peak, bankroll)
        max_dd = max(max_dd, (peak - bankroll) / peak)
    n = len(launches)
    return {"final": bankroll, "trades": n, "win_rate": wins / n if n else 0,
            "max_dd": max_dd}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start-sol", type=float, default=1.0)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--per-day", type=int, default=25,
                    help="qualifying tokens entered per day (after the filter)")
    ap.add_argument("--risk", type=float, default=0.04, help="bankroll fraction per trade")
    ap.add_argument("--max-position-sol", type=float, default=0.1)
    ap.add_argument("--min-liquidity", type=float, default=30_000)
    ap.add_argument("--trail", type=float, default=0.25)
    ap.add_argument("--seeds", type=int, nargs="+",
                    default=[7, 99, 2024, 555, 13, 404, 88, 1234])
    args = ap.parse_args()

    trades = args.days * args.per_day
    results = [run_one(s, trades, args.min_liquidity, args.start_sol,
                       args.risk, args.max_position_sol, args.trail)
               for s in args.seeds]
    finals = sorted(r["final"] for r in results)
    profitable = sum(1 for f in finals if f > args.start_sol)

    print("=" * 66)
    print("  LUMURIA TURBOBOT — 1 SOL projection (CRUEL, selective + trailing)")
    print("=" * 66)
    print(f"  start {args.start_sol} SOL | {args.days} days | ~{args.per_day} "
          f"trades/day = {trades} trades")
    print(f"  entry: liquidity >= ${args.min_liquidity:,.0f} | risk "
          f"{args.risk:.0%}/trade | trailing trail {args.trail:.0%}")
    print(f"  median trades/run {median(r['trades'] for r in results):.0f} | "
          f"median win rate {median(r['win_rate'] for r in results):.0%} | "
          f"median max drawdown {median(r['max_dd'] for r in results):.0%}")
    print("-" * 66)
    print(f"  WORST  run: {finals[0]:.2f} SOL   ({_roi(finals[0], args.start_sol)})")
    print(f"  TYPICAL   : {median(finals):.2f} SOL   "
          f"({_roi(median(finals), args.start_sol)})")
    print(f"  BEST   run: {finals[-1]:.2f} SOL   ({_roi(finals[-1], args.start_sol)})")
    print(f"  profitable runs: {profitable}/{len(finals)}")
    print("-" * 66)
    print("  High variance is real: the typical run is modest, a few moon, some")
    print("  bleed. Simulated assumptions — prove it with a VPS dry-run first.")
    print("=" * 66)


def _roi(final: float, start: float) -> str:
    return f"{(final / start - 1) * 100:+.0f}%"


if __name__ == "__main__":
    main()
