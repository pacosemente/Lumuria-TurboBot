#!/usr/bin/env python3
"""Prepare the offline path: study the cruel market, evolve a strategy, and
save the brain the live bot will run. One command to get training done.

    python3 prepare.py                 # study + evolve + save brain.json
    python3 prepare.py --quick         # faster, smaller run
"""
from __future__ import annotations

import argparse
from dataclasses import asdict

from lumuria.evolution import evolve, save_brain
from lumuria.explore import analyze, explore


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="brain.json")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    tokens = 1200 if args.quick else 2500
    gens = 8 if args.quick else 15
    pop = 16 if args.quick else 28

    print("=" * 62)
    print("  LUMURIA TURBOBOT — preparing (offline learning pipeline)")
    print("=" * 62)

    print("\n[1/2] STUDY: entering every token to learn what to avoid...")
    study = analyze(explore(tokens=tokens))
    print(f"  entering everything in the cruel market: win {study['win']:.0%}, "
          f"expectancy {study['base_r']:+.2f} R (so: be selective)")
    for rec in study["recommendations"][:5]:
        print(f"  - avoid {rec.label}: {rec.bad_r:+.2f} R -> {rec.fix} "
              f"(+{rec.improvement_r:.2f} R)")

    print(f"\n[2/2] EVOLVE: breeding a strategy to survive ({gens} gens x {pop})...")
    best, fit, history, (pnl, trades) = evolve(generations=gens, pop_size=pop,
                                               tokens=tokens)
    for i, h in enumerate(history, 1):
        shown = f"{h:+.0f}" if h > -1e8 else "infeasible"
        print(f"    gen {i:>2}: best mean P&L {shown}")

    save_brain(best, args.out, meta={"fitness": fit, "trades": trades})
    print("\n  evolved brain:")
    for k, v in asdict(best).items():
        print(f"    {k:<16} {v}")
    ready = fit > 0
    print(f"\n  fitness {fit:+.0f} over {trades} trades -> "
          f"{'survives the cruel market' if ready else 'still negative'}")
    print(f"  saved -> {args.out}")
    print("\n  Next: validate on REAL data (dry-run), then study the real journal:")
    print("    live.py --brain brain.json --rpc-url <rpc> --min-liquidity 30000")
    print("    explore.py --journal lumuria_trades.jsonl   # what REAL trades say")


if __name__ == "__main__":
    main()
