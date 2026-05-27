"""Jupiter aggregator quotes: the real "can I get out, and at what cost" check.

We simulate the full round trip with quotes (no transaction is sent):
    USDC -> token   (buy)   gives tokens received + buy price impact
    token -> USDC   (sell)  gives USD returned + sell price impact, and proves
                            a sell route exists at all

A missing sell route is the strongest honeypot signal there is: if Jupiter
can't route token -> USDC for your size, you cannot exit. The gap between the
USDC you put in and the USDC you'd get back is the true round-trip friction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import http

DEFAULT_BASE = "https://lite-api.jup.ag/swap/v1"  # free tier, no key
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"
USDC_DECIMALS = 6


@dataclass
class Quote:
    route_exists: bool
    out_amount: int = 0
    price_impact_pct: float | None = None  # fraction, 0-1


@dataclass
class RoundTrip:
    buy: Quote
    sell: Quote
    in_usd: float
    out_usd: float | None       # USD you'd recover selling back
    roundtrip_cost_pct: float | None  # fraction lost to impact + routing


def parse_quote(payload: dict[str, Any]) -> Quote:
    if not payload or payload.get("error") or "outAmount" not in payload:
        return Quote(route_exists=False)
    try:
        out_amount = int(payload["outAmount"])
    except (TypeError, ValueError):
        return Quote(route_exists=False)
    impact_raw = payload.get("priceImpactPct")
    try:
        impact = float(impact_raw) if impact_raw is not None else None
    except (TypeError, ValueError):
        impact = None
    return Quote(route_exists=True, out_amount=out_amount, price_impact_pct=impact)


def fetch_quote(
    input_mint: str,
    output_mint: str,
    amount_base: int,
    *,
    slippage_bps: int = 500,
    base_url: str = DEFAULT_BASE,
) -> Quote:
    try:
        payload = http.get_json(f"{base_url}/quote", params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": int(amount_base),
            "slippageBps": slippage_bps,
        })
    except http.SourceError as e:
        # A 4xx here usually means "no route" rather than a transport failure.
        if isinstance(e, http.SourceUnavailable):
            raise
        return Quote(route_exists=False)
    return parse_quote(payload)


def fetch_quote_raw(
    input_mint: str,
    output_mint: str,
    amount_base: int,
    *,
    slippage_bps: int = 500,
    base_url: str = DEFAULT_BASE,
) -> dict | None:
    """Raw quote dict, needed verbatim as the `quoteResponse` for /swap."""
    try:
        payload = http.get_json(f"{base_url}/quote", params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": int(amount_base),
            "slippageBps": slippage_bps,
        })
    except http.SourceError as e:
        if isinstance(e, http.SourceUnavailable):
            raise
        return None
    if not payload or payload.get("error") or "outAmount" not in payload:
        return None
    return payload


def fetch_swap_transaction(
    quote_raw: dict,
    user_pubkey: str,
    *,
    base_url: str = DEFAULT_BASE,
    priority_lamports: object = "auto",
) -> str | None:
    """Ask Jupiter to build the swap; returns a base64 VersionedTransaction."""
    payload = http.post_json(f"{base_url}/swap", {
        "quoteResponse": quote_raw,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
        "prioritizationFeeLamports": priority_lamports,
    })
    return (payload or {}).get("swapTransaction")


def roundtrip_usdc(
    mint: str,
    position_usd: float,
    *,
    slippage_bps: int = 500,
    base_url: str = DEFAULT_BASE,
) -> RoundTrip:
    in_base = int(position_usd * (10 ** USDC_DECIMALS))
    buy = fetch_quote(USDC, mint, in_base, slippage_bps=slippage_bps, base_url=base_url)
    if not buy.route_exists or buy.out_amount <= 0:
        return RoundTrip(buy=buy, sell=Quote(route_exists=False),
                         in_usd=position_usd, out_usd=None, roundtrip_cost_pct=None)

    sell = fetch_quote(mint, USDC, buy.out_amount,
                       slippage_bps=slippage_bps, base_url=base_url)
    if not sell.route_exists:
        return RoundTrip(buy=buy, sell=sell, in_usd=position_usd,
                         out_usd=None, roundtrip_cost_pct=None)

    out_usd = sell.out_amount / (10 ** USDC_DECIMALS)
    cost = (position_usd - out_usd) / position_usd if position_usd else None
    return RoundTrip(buy=buy, sell=sell, in_usd=position_usd,
                     out_usd=out_usd, roundtrip_cost_pct=cost)
