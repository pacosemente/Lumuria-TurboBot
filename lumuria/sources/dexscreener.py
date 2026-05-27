"""Dexscreener: rich per-token market data, used to cross-confirm GeckoTerminal.

Free, no key. We pick the deepest Solana pair for a mint and read its price,
liquidity, volume and buy/sell counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import http
from ..realtime.view import Market

BASE = "https://api.dexscreener.com/latest/dex"


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _age_minutes_ms(created_ms: Any) -> float | None:
    ms = _f(created_ms)
    if ms is None:
        return None
    created = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return round((datetime.now(timezone.utc) - created).total_seconds() / 60.0, 1)


def _best_solana_pair(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    sol = [p for p in pairs if p.get("chainId") == "solana"]
    if not sol:
        return None
    return max(sol, key=lambda p: _f((p.get("liquidity") or {}).get("usd")) or 0.0)


def parse_token(payload: dict[str, Any]) -> Market | None:
    pair = _best_solana_pair(payload.get("pairs") or [])
    if pair is None:
        return None
    txns = (pair.get("txns") or {}).get("h24") or {}
    return Market(
        price_usd=_f(pair.get("priceUsd")),
        liquidity_usd=_f((pair.get("liquidity") or {}).get("usd")),
        fdv_usd=_f(pair.get("fdv")),
        volume_h24_usd=_f((pair.get("volume") or {}).get("h24")),
        age_minutes=_age_minutes_ms(pair.get("pairCreatedAt")),
        buys_h24=txns.get("buys"),
        sells_h24=txns.get("sells"),
        price_change_h1_pct=_f((pair.get("priceChange") or {}).get("h1")),
    )


def fetch_token_market(mint: str) -> Market | None:
    payload = http.get_json(f"{BASE}/tokens/{mint}")
    return parse_token(payload)
