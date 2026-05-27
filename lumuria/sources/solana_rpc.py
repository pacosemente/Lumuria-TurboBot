"""Read a mint's authorities straight from the chain via JSON-RPC.

This is the ground truth for the two deadliest signals:
  - freeze_authority set -> they can freeze your tokens (honeypot)
  - mint_authority set    -> they can mint and dump on you (rug)

Works for tokens too new to be indexed by RugCheck. Point `rpc_url` at your own
VPS/Helius/QuickNode node for speed and to avoid public-endpoint rate limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import http
from ..realtime.view import Authorities

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def _extensions(info: dict[str, Any]) -> dict[str, dict]:
    """Map a Token-2022 mint's extensions by name."""
    out: dict[str, dict] = {}
    for ext in info.get("extensions") or []:
        name = ext.get("extension")
        if name:
            out[name] = ext.get("state") or {}
    return out


def parse_account_info(payload: dict[str, Any]) -> Authorities:
    value = (payload.get("result") or {}).get("value") or {}
    data = value.get("data") or {}
    info = (data.get("parsed") or {}).get("info") or {}
    program = data.get("program")  # "spl-token" or "spl-token-2022"
    exts = _extensions(info)

    default_frozen = None
    if "defaultAccountState" in exts:
        default_frozen = exts["defaultAccountState"].get("accountState") == "frozen"

    transfer_fee_bps = None
    if "transferFeeConfig" in exts:
        cfg = exts["transferFeeConfig"]
        newer = cfg.get("newerTransferFee") or {}
        transfer_fee_bps = newer.get("transferFeeBasisPoints")

    return Authorities(
        mint_authority=info.get("mintAuthority"),
        freeze_authority=info.get("freezeAuthority"),
        decimals=info.get("decimals"),
        program=program,
        default_account_frozen=default_frozen,
        transfer_fee_bps=transfer_fee_bps,
        has_transfer_hook=("transferHook" in exts) if exts or program else None,
        has_permanent_delegate=("permanentDelegate" in exts) if exts or program else None,
    )


def fetch_authorities(mint: str, rpc_url: str = PUBLIC_RPC) -> Authorities:
    payload = http.post_json(rpc_url, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [mint, {"encoding": "jsonParsed"}],
    })
    return parse_account_info(payload)


@dataclass
class SimResult:
    ok: bool
    err: Any = None
    logs: list[str] = field(default_factory=list)
    units_consumed: int | None = None


def parse_simulation(payload: dict[str, Any]) -> SimResult:
    value = (payload.get("result") or {}).get("value") or {}
    err = value.get("err")
    return SimResult(
        ok=err is None,
        err=err,
        logs=value.get("logs") or [],
        units_consumed=value.get("unitsConsumed"),
    )


def simulate_transaction(b64_tx: str, rpc_url: str = PUBLIC_RPC) -> SimResult:
    """Ask the chain to dry-run a (serialized, base64) transaction.

    No signature and no funds needed: the blockhash is replaced and signature
    verification is skipped, so this previews whether the swap would land.
    """
    payload = http.post_json(rpc_url, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "simulateTransaction",
        "params": [b64_tx, {
            "sigVerify": False,
            "replaceRecentBlockhash": True,
            "encoding": "base64",
        }],
    })
    return parse_simulation(payload)


@dataclass
class SigStatus:
    found: bool
    confirmed: bool
    err: Any = None


def parse_signature_status(payload: dict[str, Any]) -> SigStatus:
    value = (payload.get("result") or {}).get("value") or [None]
    info = value[0] if value else None
    if not info:
        return SigStatus(found=False, confirmed=False)
    status = info.get("confirmationStatus")
    return SigStatus(
        found=True,
        confirmed=status in ("confirmed", "finalized") and info.get("err") is None,
        err=info.get("err"),
    )


def get_signature_status(signature: str, rpc_url: str = PUBLIC_RPC) -> SigStatus:
    payload = http.post_json(rpc_url, {
        "jsonrpc": "2.0", "id": 1, "method": "getSignatureStatuses",
        "params": [[signature], {"searchTransactionHistory": True}],
    })
    return parse_signature_status(payload)


def parse_token_balance(payload: dict[str, Any]) -> int:
    """Sum raw token amounts across all of an owner's accounts for one mint."""
    total = 0
    for acct in (payload.get("result") or {}).get("value") or []:
        info = (((acct.get("account") or {}).get("data") or {})
                .get("parsed") or {}).get("info") or {}
        amount = (info.get("tokenAmount") or {}).get("amount")
        try:
            total += int(amount)
        except (TypeError, ValueError):
            pass
    return total


def get_token_balance(owner: str, mint: str, rpc_url: str = PUBLIC_RPC) -> int:
    payload = http.post_json(rpc_url, {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
        "params": [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
    })
    return parse_token_balance(payload)
