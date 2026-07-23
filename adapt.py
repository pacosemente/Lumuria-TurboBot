#!/usr/bin/env python3
"""Evolve the brain from REAL trades: tighten entry filters where the live
journal proves a token class loses money. Run it periodically as real data
accumulates (e.g. weekly, or on a schedule).

    python3 adapt.py --brain brain.json --journal lumuria_trades.jsonl
"""
from __future__ import annotations

import argparse

from lumuria.adapt import adapt_brain
from lumuria.evolution import describe, load_brain, save_brain
from lumuria.realtime.journal import TradeJournal


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--brain", default="brain.json")
    ap.add_argument("--journal", default="lumuria_trades.jsonl")
    ap.add_argument("--min-sample", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true", help="show changes, don't save")
    args = ap.parse_args()

    brain = load_brain(args.brain)
    records = TradeJournal(args.journal).feature_records()
    print(f"  studying {len(records)} real trades from {args.journal}")
    if len(records) < args.min_sample:
        print(f"  not enough real data yet (need >= {args.min_sample}); "
              "keep the dry-run running.")
        return

    new_brain, changes = adapt_brain(brain, records, min_sample=args.min_sample)
    if not changes:
        print("  no change — real data does not justify tightening anything yet.")
        return

    print("  the bot learned from real trades and wants to tighten:")
    for c in changes:
        print(f"    - {c}")
    print("\n  new brain (every gene has a live meaning):")
    for gene, value, meaning in describe(new_brain):
        print(f"    {gene:<16} {value:>8}  {meaning}")
    if args.dry_run:
        print("\n  --dry-run: not saved.")
    else:
        save_brain(new_brain, args.brain, meta={"adapted_from": args.journal,
                                                "real_trades": len(records),
                                                "changes": changes})
        print(f"\n  saved -> {args.brain}. Restart live.py to use the evolved brain.")


if __name__ == "__main__":
    main()
