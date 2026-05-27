"""RugCheck.xyz: aggregated scam/rug risk report for a Solana mint.

Free, no key. Gives a risk score, named risks, mint/freeze authorities, top
holder distribution and LP lock status. Brand-new tokens may not be indexed
yet, which is why we also read authorities straight from the chain (rpc.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import http

BASE = "https://api.rugcheck.xyz/v1"


@dataclass
class RugcheckResult:
    score: int | None = None
    rugged: bool | None = None
    risks: list[str] = field(default_factory=list)
    mint_authority: str | None = None
    freeze_authority: str | None = None
    decimals: int | None = None
    holder_count: int | None = None
    top_holder_pct: float | None = None   # 0-1
    top10_pct: float | None = None         # 0-1
    insiders_pct: float | None = None      # 0-1
    lp_locked_pct: float | None = None     # 0-1


def _pct_to_fraction(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 100.0 if f > 1.0 else f  # RugCheck reports percentages (0-100)


def parse_report(payload: dict[str, Any]) -> RugcheckResult:
    token = payload.get("token") or {}
    holders = payload.get("topHolders") or []

    top_holder = _pct_to_fraction(holders[0].get("pct")) if holders else None
    top10 = None
    if holders:
        s = sum((_pct_to_fraction(h.get("pct")) or 0.0) for h in holders[:10])
        top10 = min(s, 1.0)
    insiders = None
    if holders:
        ins = sum((_pct_to_fraction(h.get("pct")) or 0.0)
                  for h in holders if h.get("insider"))
        insiders = min(ins, 1.0) if ins else None

    lp_locked = None
    for m in payload.get("markets") or []:
        lp = m.get("lp") or {}
        frac = _pct_to_fraction(lp.get("lpLockedPct"))
        if frac is not None:
            lp_locked = max(lp_locked or 0.0, frac)

    risks = [r.get("name", "") for r in (payload.get("risks") or []) if r.get("name")]

    return RugcheckResult(
        score=payload.get("score"),
        rugged=payload.get("rugged"),
        risks=risks,
        mint_authority=token.get("mintAuthority") or payload.get("mintAuthority"),
        freeze_authority=token.get("freezeAuthority") or payload.get("freezeAuthority"),
        decimals=token.get("decimals"),
        holder_count=payload.get("totalHolders") or len(holders) or None,
        top_holder_pct=top_holder,
        top10_pct=top10,
        insiders_pct=insiders,
        lp_locked_pct=lp_locked,
    )


def fetch_report(mint: str) -> RugcheckResult:
    payload = http.get_json(f"{BASE}/tokens/{mint}/report")
    return parse_report(payload)
