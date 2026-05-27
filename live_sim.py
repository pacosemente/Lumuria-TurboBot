#!/usr/bin/env python3
"""Live paper-trading simulation on REAL Solana data. No real money is spent.

Run this on your VPS (the Claude web sandbox blocks the data APIs). It scans
new tokens, enters the ones that clear every safety gate (liquidity, honeypot,
scam, slippage) at their real current price, then follows real price moves and
applies your exit strategy — reporting bankroll and ROI so you can see whether
the edge is real before risking a cent.

    python3 live_sim.py --watch --interval 25 --rpc-url https://your-rpc \
        --start-bankroll 500 --sizer rampup --strategy scaled

Let it run for a while: tokens need time to move for P&L to mean anything.
"""
from __future__ import annotations

import argparse
import sys
import time

from lumuria.execution import PaperBroker
from lumuria.realtime import Scanner, ScannerConfig
from lumuria.realtime.decision import DecisionConfig
from lumuria.realtime.papertrade import LivePaperTrader
from lumuria.sizing import BankrollFractionSizer, FixedSizer, RampUpSizer
from lumuria.sources import dexscreener, http, solana_rpc
from lumuria.strategies import FixedStopTarget, ScaledExit, TrailingStop


def make_sizer(name: str, base: float):
    if name == "fixed":
        return FixedSizer(amount=base)
    if name == "bankroll":
        return BankrollFractionSizer(fraction=0.05, min_usd=base)
    return RampUpSizer(base=base, step=1.6, cap=base * 10)


def make_strategy_factory(name: str):
    if name == "fixed":
        return lambda: FixedStopTarget(stop_pct=0.30, target_pct=1.00)
    if name == "trailing":
        return lambda: TrailingStop(hard_stop_pct=0.30, arm_pct=0.20, trail_pct=0.35)
    return lambda: ScaledExit(stop_pct=0.30, first_target_pct=0.50,
                              first_fraction=0.50, trail_pct=0.35)


def fresh_price(mint: str, fallback: float | None) -> float | None:
    try:
        m = dexscreener.fetch_token_market(mint)
        if m and m.price_usd:
            return m.price_usd
    except http.SourceError:
        pass
    return fallback


def print_report(trader: LivePaperTrader) -> None:
    m = trader.metrics()
    deployed = trader.equity_open_cost
    print("\n" + "-" * 60)
    print(f"  bankroll (cash)  : ${trader.bankroll:,.2f}")
    print(f"  open positions   : {len(trader.open)}  (${deployed:,.2f} deployed)")
    print(f"  closed trades    : {m.trades}  ({m.wins}W / {m.losses}L, "
          f"win rate {m.win_rate:.0%})")
    print(f"  expectancy       : ${m.expectancy_usd:+,.2f}/trade ({m.expectancy_r:+.2f} R)")
    print(f"  realized P&L     : ${m.total_pnl_usd:+,.2f}  |  max DD ${m.max_drawdown_usd:,.2f}")
    print(f"  ROI (incl. open) : {trader.roi_pct:+.1%}  on ${trader.starting_bankroll:,.0f}")
    print("-" * 60)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--watch", action="store_true", help="run continuously (default)")
    p.add_argument("--interval", type=float, default=25.0)
    p.add_argument("--max-cycles", type=int, default=0, help="0 = run until Ctrl-C")
    p.add_argument("--start-bankroll", type=float, default=500.0)
    p.add_argument("--base-size", type=float, default=10.0,
                   help="base/min USD per entry (start small)")
    p.add_argument("--max-position", type=float, default=50.0,
                   help="position size used for the slippage gate (your ceiling)")
    p.add_argument("--sizer", choices=["fixed", "bankroll", "rampup"], default="rampup")
    p.add_argument("--strategy", choices=["fixed", "trailing", "scaled"], default="scaled")
    p.add_argument("--min-liquidity", type=float, default=10_000.0)
    p.add_argument("--max-slippage", type=float, default=0.10)
    p.add_argument("--rpc-url", default="")
    args = p.parse_args()

    scanner = Scanner(ScannerConfig(
        position_usd=args.max_position,
        rpc_url=args.rpc_url or solana_rpc.PUBLIC_RPC,
        slippage_bps=int(args.max_slippage * 10_000),
        decision=DecisionConfig(min_liquidity_usd=args.min_liquidity,
                                max_slippage_pct=args.max_slippage),
    ))
    trader = LivePaperTrader(
        broker=PaperBroker(),
        strategy_factory=make_strategy_factory(args.strategy),
        sizer=make_sizer(args.sizer, args.base_size),
        starting_bankroll=args.start_bankroll,
    )

    print("=" * 60)
    print("  LUMURIA TURBOBOT — live paper simulation (REAL data, fake money)")
    print(f"  sizer {trader.sizer.name} | strategy {args.strategy} "
          f"| start ${args.start_bankroll:,.0f}")
    print("=" * 60)

    last_price: dict[str, float] = {}
    cycle = 0
    try:
        while args.max_cycles == 0 or cycle < args.max_cycles:
            cycle += 1
            results = scanner.scan_once()
            seen = {v.mint: v.market.price_usd for v, _ in results if v.market.price_usd}

            for view, decision in results:
                if decision.enter and view.mint not in trader.open:
                    size = trader.open_position(view.mint, view.symbol,
                                                view.market.price_usd)
                    if size:
                        last_price[view.mint] = view.market.price_usd
                        print(f"[ENTER] {view.symbol:<10} ${size:,.2f} @ "
                              f"${view.market.price_usd:.8f}  liq "
                              f"${view.market.liquidity_usd:,.0f}")

            for mint in list(trader.open):
                price = fresh_price(mint, seen.get(mint, last_price.get(mint)))
                if not price:
                    continue
                last_price[mint] = price
                trade = trader.tick(mint, price)
                if trade:
                    print(f"[EXIT ] {trade.symbol:<10} P&L ${trade.pnl_usd:+,.2f} "
                          f"({trade.pnl_r:+.2f} R)  bankroll ${trader.bankroll:,.2f}")

            print(f"  cycle {cycle}: scanned {len(results)}, "
                  f"open {len(trader.open)}, closed {len(trader.trades)}")
            if args.max_cycles == 0 or cycle < args.max_cycles:
                time.sleep(args.interval)
    except http.SourceError as e:
        print(f"\n  Data source unreachable: {e}", file=sys.stderr)
        print("  Run this on your VPS (these APIs are blocked in the sandbox).",
              file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n  Stopping — closing open positions at last seen price...")

    for mint in list(trader.open):
        trader.force_close(mint, last_price.get(mint, 0.0))
    print_report(trader)


if __name__ == "__main__":
    main()
