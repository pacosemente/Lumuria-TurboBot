"""GeckoTerminal: discover brand-new Solana pools and read their market data.

Free, no key, ~30 req/min. Used as the primary "watch every new token" feed
and for price/liquidity/volume/age enrichment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import http
from ..realtime.view import Market

BASE = "https://api.geckoterminal.com/api/v2"
NETWORK = "solana"


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    f = _f(v)
    return int(f) if f is not None else None


def _mint_from_token_id(token_id: str | None) -> str | None:
    # GeckoTerminal token ids look like "solana_<mint>".
    if not token_id:
        return None
    return token_id.split("_", 1)[1] if "_" in token_id else token_id


def _age_minutes(created_at: str | None) -> float | None:
    if not created_at:
        return None
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return round(delta.total_seconds() / 60.0, 1)
    except ValueError:
        return None


def parse_market(attrs: dict[str, Any]) -> Market:
    txns = attrs.get("transactions") or {}
    h24 = txns.get("h24") or {}
    vol = attrs.get("volume_usd") or {}
    chg = attrs.get("price_change_percentage") or {}
    return Market(
        price_usd=_f(attrs.get("base_token_price_usd")),
        liquidity_usd=_f(attrs.get("reserve_in_usd")),
        fdv_usd=_f(attrs.get("fdv_usd")),
        volume_h24_usd=_f(vol.get("h24")),
        age_minutes=_age_minutes(attrs.get("pool_created_at")),
        buys_h24=_i(h24.get("buys")),
        sells_h24=_i(h24.get("sells")),
        price_change_h1_pct=_f(chg.get("h1")),
    )


def parse_new_pools(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return lightweight discovery records: mint, pool, name, dex, market."""
    out: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        rel = item.get("relationships", {})
        base = (rel.get("base_token") or {}).get("data") or {}
        dex = (rel.get("dex") or {}).get("data") or {}
        mint = _mint_from_token_id(base.get("id"))
        if not mint:
            continue
        out.append({
            "mint": mint,
            "pool_address": attrs.get("address", ""),
            "name": attrs.get("name", ""),
            "dex": dex.get("id", ""),
            "market": parse_market(attrs),
        })
    return out


def fetch_new_pools(*, page: int = 1) -> list[dict[str, Any]]:
    payload = http.get_json(f"{BASE}/networks/{NETWORK}/new_pools",
                            params={"page": page})
    return parse_new_pools(payload)


def fetch_pool_market(pool_address: str) -> Market:
    payload = http.get_json(f"{BASE}/networks/{NETWORK}/pools/{pool_address}")
    attrs = (payload.get("data") or {}).get("attributes", {})
    return parse_market(attrs)
