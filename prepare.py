#!/usr/bin/env python3
"""Prepare the offline path: study the cruel market, evolve a strategy, and
save the brain the live bot will run. One command to get training done.

    python3 prepare.py                    # auto-sizes to this machine
    python3 prepare.py --profile small    # 1 vCPU VPS
    python3 prepare.py --quick            # fast local run (same as --profile local)
"""
from __future__ import annotations

import argparse

from lumuria import profiles
from lumuria.evolution import describe, evolve, save_brain
from lumuria.explore import analyze, explore


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="brain.json")
    ap.add_argument("--profile", default="auto",
                    choices=["auto", "local", "small", "medium", "large"],
                    help="machine profile: training depth scaled to hardware")
    ap.add_argument("--quick", action="store_true",
                    help="shortcut for --profile local")
    args = ap.parse_args()

    prof = profiles.get("local" if args.quick else args.profile)
    tokens, gens, pop = prof.tokens, prof.generations, prof.pop_size

    print("=" * 62)
    print("  LUMURIA TURBOBOT — preparing (offline learning pipeline)")
    print("=" * 62)
    print(f"  profile: {prof.name} — {prof.label}")
    print(f"           {tokens} tokens x {gens} generations x {pop} genomes")

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
        print(f"    gen {i:>2}: best true value {shown}")

    save_brain(best, args.out, meta={"fitness": fit, "trades": trades,
                                     "profile": prof.name})
    print("\n  evolved brain (every gene has a live meaning):")
    for gene, value, meaning in describe(best):
        print(f"    {gene:<16} {value:>8}  {meaning}")
    ready = fit > 0
    print(f"\n  true value {fit:+.0f} (mean P&L - luck spread - drawdown tax) "
          f"over {trades} trades -> "
          f"{'survives the cruel market' if ready else 'still negative'}")
    print(f"  saved -> {args.out}")
    print("\n  Next: validate on REAL data (dry-run), then study the real journal:")
    print("    live.py --brain brain.json --rpc-url <rpc> --min-liquidity 30000")
    print("    explore.py --journal lumuria_trades.jsonl   # what REAL trades say")


if __name__ == "__main__":
    main()
