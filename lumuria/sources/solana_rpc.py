"""Read a mint's authorities straight from the chain via JSON-RPC.

This is the ground truth for the two deadliest signals:
  - freeze_authority set -> they can freeze your tokens (honeypot)
  - mint_authority set    -> they can mint and dump on you (rug)

Works for tokens too new to be indexed by RugCheck. Point `rpc_url` at your own
VPS/Helius/QuickNode node for speed and to avoid public-endpoint rate limits.
"""
from __future__ import annotations

from typing import Any

from . import http
from ..realtime.view import Authorities

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def parse_account_info(payload: dict[str, Any]) -> Authorities:
    value = (payload.get("result") or {}).get("value") or {}
    data = value.get("data") or {}
    info = (data.get("parsed") or {}).get("info") or {}
    return Authorities(
        mint_authority=info.get("mintAuthority"),
        freeze_authority=info.get("freezeAuthority"),
        decimals=info.get("decimals"),
    )


def fetch_authorities(mint: str, rpc_url: str = PUBLIC_RPC) -> Authorities:
    payload = http.post_json(rpc_url, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint, {"encoding": "jsonParsed"}],
    })
    return parse_account_info(payload)
