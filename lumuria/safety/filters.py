"""Pre-buy safety checks.

These heuristics don't make money directly — they avoid the single worst
outcome in sniping, the -100% from a rug or honeypot. Skipping a few winners
is a fair price for dodging those.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import TokenSnapshot


@dataclass
class SafetyConfig:
    min_liquidity_usd: float = 8_000.0
    min_holders: int = 60
    max_top_holder_pct: float = 0.35
    require_lp_locked: bool = True
    require_mint_renounced: bool = False


class SafetyFilter:
    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config or SafetyConfig()

    def evaluate(self, snap: TokenSnapshot) -> tuple[bool, list[str]]:
        c = self.config
        reasons: list[str] = []

        if snap.liquidity_usd < c.min_liquidity_usd:
            reasons.append(f"low liquidity (${snap.liquidity_usd:,.0f})")
        if snap.holders < c.min_holders:
            reasons.append(f"few holders ({snap.holders})")
        if snap.top_holder_pct > c.max_top_holder_pct:
            reasons.append(f"whale holds {snap.top_holder_pct:.0%}")
        if c.require_lp_locked and not snap.lp_locked:
            reasons.append("LP not locked")
        if c.require_mint_renounced and not snap.mint_renounced:
            reasons.append("mint not renounced")

        return (len(reasons) == 0, reasons)
