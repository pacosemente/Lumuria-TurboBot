#!/usr/bin/env python3
"""Offline DEMO of the bot operating — no network, no VPS, no money.

It feeds simulated token launches (most are scams/rugs, a few moon) through the
exact same safety decision engine the live bot uses, then paper-trades the ones
that pass with a SOL budget and TP/SL exits. You get the live-style play-by-play
right here, so you can see what the real thing looks like before wiring a VPS.

    python3 demo.py                 # quick run
    python3 demo.py --tokens 60 --delay 0.15   # slower, more lifelike
"""
from __future__ import annotations

import argparse
import random
import time

from lumuria.feeds.simulated import SimulatedFeed
from lumuria.models import Fate
from lumuria.realtime.decision import Category, DecisionConfig, evaluate
from lumuria.realtime.simsource import synth_view

SOL_USD = 150.0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tokens", type=int, default=60)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--budget-sol", type=float, default=1.0)
    p.add_argument("--per-trade-sol", type=float, default=0.05)
    p.add_argument("--take-profit", type=float, default=2.0)
    p.add_argument("--stop", type=float, default=0.6)
    p.add_argument("--max-slippage", type=float, default=0.08)
    p.add_argument("--min-liquidity", type=float, default=15_000.0)
    p.add_argument("--delay", type=float, default=0.0, help="seconds between lines")
    args = p.parse_args()

    rng = random.Random(args.seed)
    launches = SimulatedFeed(n=args.tokens, seed=args.seed).materialize()
    cfg = DecisionConfig(min_liquidity_usd=args.min_liquidity,
                         max_slippage_pct=args.max_slippage)
    position_usd = args.per_trade_sol * SOL_USD

    print("=" * 62)
    print("  LUMURIA TURBOBOT — DEMO (offline, simulated market, fake money)")
    print(f"  budget {args.budget_sol} SOL | per trade {args.per_trade_sol} SOL "
          f"| TP x{args.take_profit} | SL x{args.stop}")
    print("=" * 62)

    committed = realized = 0.0
    wins = losses = 0
    dodged = {c.value: 0 for c in Category}
    dodged_scams = 0

    def out(line: str) -> None:
        print(line)
        if args.delay:
            time.sleep(args.delay)

    for launch in launches:
        view = synth_view(launch, position_usd, rng)
        decision = evaluate(view, cfg, position_usd)

        if not decision.enter:
            cats = {r.category for r in decision.reasons}
            for c in cats:
                dodged[c.value] += 1
            if launch.fate in (Fate.HONEYPOT, Fate.RUG) and (
                    Category.HONEYPOT in cats or Category.SCAM in cats):
                dodged_scams += 1
            reason = decision.reasons[0].text
            out(f"[skip ] {view.symbol:<10} {reason}")
            continue

        if committed + args.per_trade_sol > args.budget_sol + 1e-9:
            out(f"[hold ] {view.symbol:<10} passed, but budget full")
            continue

        # Paper-enter at launch price, then walk its real path with TP/SL.
        entry = launch.path[0].price
        sol_in = args.per_trade_sol
        committed += sol_in
        out(f"[BUY  ] {view.symbol:<10} {sol_in:.4f} SOL @ {entry:.6f}  "
            f"impact {view.sell_quote.price_impact_pct:.1%}  liq "
            f"${view.market.liquidity_usd:,.0f}")

        exit_mult, tag = launch.path[-1].price / entry, "END"
        for tick in launch.path[1:]:
            mult = tick.price / entry
            if mult >= args.take_profit:
                exit_mult, tag = mult, "TP"
                break
            if mult <= args.stop:
                exit_mult, tag = mult, "SL"
                break

        got = sol_in * exit_mult
        realized += got
        committed -= sol_in  # budget freed on exit
        pnl = got - sol_in
        wins += pnl > 0
        losses += pnl <= 0
        out(f"[SELL {tag}] {view.symbol:<10} {sol_in:.4f}->{got:.4f} SOL "
            f"({pnl:+.4f})")

    n = wins + losses
    print("\n" + "-" * 62)
    print(f"  trades: {n}  ({wins}W / {losses}L, "
          f"win rate {wins / n:.0%})" if n else "  no trades")
    print(f"  realized P&L: {realized - (wins + losses) * args.per_trade_sol:+.4f} SOL "
          f"(~${(realized - n * args.per_trade_sol) * SOL_USD:+,.0f})")
    print(f"  scams/honeypots dodged: {dodged_scams}  "
          f"(honeypot blocks {dodged['honeypot']}, scam {dodged['scam']}, "
          f"slippage {dodged['slippage']}, liquidity {dodged['liquidity']})")
    print("-" * 62)
    print("  Simulated data — a lab to see behavior, not a profit promise.")


if __name__ == "__main__":
    main()
