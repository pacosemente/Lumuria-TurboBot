"""Adapt the brain from REAL trades: when the live journal shows a class of
tokens lost money, tighten the matching entry filter. It only ever tightens
(becomes more selective) — never loosens — so learning from real data can make
the bot safer but never recklessly looser. This is the real-market evolution
loop, applied with evidence, not magic.
"""
from __future__ import annotations

from dataclasses import replace

from .evolution import Genome
from .explore import analyze


def adapt_brain(brain: Genome, real_records: list[dict], *,
                min_sample: int = 20) -> tuple[Genome, list[str]]:
    if not real_records:
        return brain, []
    res = analyze(real_records, min_sample=min_sample)
    base_r = res["base_r"]
    seg = {label: (n, win, r) for label, n, win, r in res["segments"]}
    g = replace(brain)
    changes: list[str] = []

    def bad(label: str) -> tuple[int, float] | None:
        n, _win, r = seg.get(label, (0, 0.0, 0.0))
        return (n, r) if (n >= min_sample and r < base_r) else None

    # Raise the liquidity floor if low-liquidity tokens are losing for real.
    for label, threshold in (("liquidity < $30k", 30_000.0),
                             ("liquidity < $15k", 15_000.0)):
        hit = bad(label)
        if hit and threshold > g.min_liquidity:
            g.min_liquidity = threshold
            changes.append(f"min_liquidity -> ${threshold:,.0f} "
                           f"(real {label}: {hit[1]:+.2f} R over {hit[0]} trades)")

    hit = bad("whale > 35%")
    if hit and g.max_top_holder > 0.35:
        g.max_top_holder = 0.35
        changes.append(f"max_top_holder -> 35% "
                       f"(real whales: {hit[1]:+.2f} R over {hit[0]} trades)")

    hit = bad("holders < 100")
    if hit and g.min_holders < 100:
        g.min_holders = 100
        changes.append(f"min_holders -> 100 "
                       f"(real low-holder: {hit[1]:+.2f} R over {hit[0]} trades)")

    return g.clamped(), changes
