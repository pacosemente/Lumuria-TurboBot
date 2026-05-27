#!/usr/bin/env python3
"""Train (evolve) the strategy against the cruel market and save the best brain.

A genetic algorithm breeds parameter sets that survive the harsh simulated
market; over generations the strategy adapts. The winner is written to a brain
file the live bot can load with --brain. No network, no money.

    python3 evolve.py --generations 15 --pop 30 --out brain.json
"""
from __future__ import annotations

import argparse
from dataclasses import asdict

from lumuria.evolution import evolve, save_brain


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--generations", type=int, default=12)
    ap.add_argument("--pop", type=int, default=24)
    ap.add_argument("--tokens", type=int, default=1500)
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 99, 2024, 555])
    ap.add_argument("--min-trades", type=int, default=60,
                    help="min total trades a genome must take to be viable")
    ap.add_argument("--out", default="brain.json")
    args = ap.parse_args()

    print("=" * 60)
    print("  LUMURIA TURBOBOT — evolving in the cruel market")
    print(f"  {args.generations} generations x {args.pop} genomes "
          f"x {len(args.seeds)} seeds")
    print("=" * 60)

    best, fit, history, (pnl, trades) = evolve(
        generations=args.generations, pop_size=args.pop, seeds=tuple(args.seeds),
        tokens=args.tokens, min_total_trades=args.min_trades)

    print("\n  learning curve (best mean P&L per generation):")
    for i, h in enumerate(history, 1):
        bar = "#" * max(0, int(h / 50)) if h > 0 else ""
        shown = f"{h:+.1f}" if h > -1e8 else "infeasible"
        print(f"    gen {i:>2}: {shown:>12}  {bar}")

    print("\n  best evolved brain:")
    for k, v in asdict(best).items():
        print(f"    {k:<16} {v}")
    print(f"\n  fitness (mean P&L/seed): {fit:+.1f}  over {trades} trades total")
    verdict = "survives the cruel market (positive)" if fit > 0 \
        else "still negative — the cruel market wins at this volume"
    print(f"  verdict: {verdict}")

    save_brain(best, args.out, meta={"fitness": fit, "trades": trades,
                                     "seeds": args.seeds})
    print(f"\n  saved brain -> {args.out}  (load it live with: live.py --brain {args.out})")


if __name__ == "__main__":
    main()
