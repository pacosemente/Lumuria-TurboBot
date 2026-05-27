#!/usr/bin/env python3
"""Watch the bot study: it enters EVERY token in the cruel simulation (making
mistakes on purpose) and reports, from the outcomes, what it needs to improve.
Offline, no money. With --loop it never stops — each round studies more tokens
and refines the advice.

    python3 explore.py                  # one study pass
    python3 explore.py --loop           # study forever, accelerating
"""
from __future__ import annotations

import argparse
import time

from lumuria.explore import analyze, explore


def report(round_no: int, tokens: int, result: dict) -> None:
    print("\n" + "=" * 64)
    tag = f"STUDY ROUND {round_no}" if round_no else "STUDY"
    print(f"  LUMURIA TURBOBOT — {tag}  (entered every token: {result['n']})")
    print("=" * 64)
    print(f"  baseline (enter everything): win {result['win']:.0%} | "
          f"expectancy {result['base_r']:+.2f} R")
    print("-" * 64)
    print("  WHAT EACH TOKEN TYPE DID:")
    for label, n, win, r in result["segments"]:
        if n:
            print(f"    {label:<22} {n:>5} trades  win {win:>4.0%}  {r:+.2f} R")
    print("-" * 64)
    print("  WHAT I NEED TO IMPROVE (ranked by impact):")
    if not result["recommendations"]:
        print("    nothing clear this round — gather more data")
    for rec in result["recommendations"]:
        print(f"    - avoid {rec.label}: {rec.bad_n} trades at {rec.bad_r:+.2f} R "
              f"-> {rec.fix} (lifts expectancy {rec.improvement_r:+.2f} R)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tokens", type=int, default=2000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 99, 2024])
    ap.add_argument("--loop", action="store_true", help="study forever, accelerating")
    ap.add_argument("--round-seconds", type=float, default=2.0)
    ap.add_argument("--max-tokens", type=int, default=12000)
    args = ap.parse_args()

    round_no = 0
    tokens = args.tokens
    try:
        while True:
            round_no += 1
            result = analyze(explore(seeds=tuple(args.seeds), tokens=tokens))
            report(round_no if args.loop else 0, tokens, result)
            if not args.loop:
                break
            tokens = min(tokens + args.tokens, args.max_tokens)  # study more each round
            time.sleep(args.round_seconds)
    except KeyboardInterrupt:
        print("\n  Stopped studying.")


if __name__ == "__main__":
    main()
