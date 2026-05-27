"""Real swap executor (Jupiter) with hard safety rails.

Defaults to DRY-RUN: it quotes and reports what it *would* do, and sends
nothing. Real execution requires `live=True` AND a keypair file on disk; the
private key is read locally and never leaves the machine.

Guard rails that always apply in live mode:
  - a hard cap on total SOL spent (`budget_sol`) and per trade (`max_position_sol`)
  - a pre-flight `simulateTransaction`: if the swap would fail on-chain, it is
    not sent (saves fees and dodges last-second honeypots)

Signing needs `solders` (pip install solders); it is imported lazily so the
rest of the bot — and all tests — run on the standard library alone.

NOTE: the real send path has not been exercised against mainnet here (the
build sandbox has no network). Run in dry-run on your VPS first, then prove it
with a single tiny trade before trusting it with the whole budget.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass

from ..sources import http, jupiter, solana_rpc

LAMPORTS_PER_SOL = 1_000_000_000


@dataclass
class ExecConfig:
    rpc_url: str = solana_rpc.PUBLIC_RPC
    jupiter_base: str = jupiter.DEFAULT_BASE
    keypair_path: str = ""
    live: bool = False
    budget_sol: float = 1.0
    max_position_sol: float = 0.05
    slippage_bps: int = 500
    confirm: bool = True              # wait for on-chain confirmation
    confirm_timeout_s: float = 30.0
    confirm_poll_s: float = 2.0
    priority_fee_lamports: object = "auto"  # higher => more likely to land
    skip_preflight: bool = False      # we already simulate; True is faster


@dataclass
class ExecResult:
    action: str          # "buy" | "sell"
    mint: str
    ok: bool
    dry_run: bool
    reason: str = ""
    sol_in: float = 0.0
    out_amount: int = 0          # token base units (buy) or lamports (sell)
    price_impact_pct: float | None = None
    signature: str | None = None


class SwapExecutor:
    def __init__(self, config: ExecConfig | None = None) -> None:
        self.config = config or ExecConfig()
        self.spent_sol = 0.0
        self._keypair = None
        self._pubkey: str | None = None

    @property
    def remaining_sol(self) -> float:
        return max(0.0, self.config.budget_sol - self.spent_sol)

    # -- keypair (live only) ----------------------------------------------

    def _load_keypair(self):
        if self._keypair is not None:
            return self._keypair
        path = self.config.keypair_path
        if not path or not os.path.exists(path):
            raise RuntimeError(f"keypair file not found: {path!r}")
        try:
            from solders.keypair import Keypair  # lazy: only needed live
        except ImportError as e:
            raise RuntimeError("live mode needs solders: pip install solders") from e
        with open(path) as f:
            secret = json.load(f)  # Solana CLI id.json: array of 64 ints
        self._keypair = Keypair.from_bytes(bytes(secret))
        self._pubkey = str(self._keypair.pubkey())
        return self._keypair

    # -- core --------------------------------------------------------------

    def buy(self, mint: str, sol_amount: float) -> ExecResult:
        cfg = self.config
        sol_amount = min(sol_amount, cfg.max_position_sol)
        if sol_amount <= 0:
            return ExecResult("buy", mint, False, not cfg.live, "size is zero")
        if sol_amount > self.remaining_sol + 1e-12:
            return ExecResult("buy", mint, False, not cfg.live,
                              f"over budget (remaining {self.remaining_sol:.4f} SOL)")

        lamports = int(sol_amount * LAMPORTS_PER_SOL)
        quote = jupiter.fetch_quote_raw(jupiter.SOL, mint, lamports,
                                        slippage_bps=cfg.slippage_bps,
                                        base_url=cfg.jupiter_base)
        if not quote:
            return ExecResult("buy", mint, False, not cfg.live, "no buy route")

        out_amount = int(quote.get("outAmount", 0))
        impact = _impact(quote)

        if not cfg.live:
            return ExecResult("buy", mint, True, True, "dry-run",
                              sol_in=sol_amount, out_amount=out_amount,
                              price_impact_pct=impact)

        return self._execute_live("buy", mint, quote, sol_in=sol_amount,
                                  out_amount=out_amount, impact=impact)

    def sell(self, mint: str, token_amount: int) -> ExecResult:
        cfg = self.config
        if token_amount <= 0:
            return ExecResult("sell", mint, False, not cfg.live, "nothing to sell")
        quote = jupiter.fetch_quote_raw(mint, jupiter.SOL, token_amount,
                                        slippage_bps=cfg.slippage_bps,
                                        base_url=cfg.jupiter_base)
        if not quote:
            # No sell route on a token we hold == trapped (honeypot realized).
            return ExecResult("sell", mint, False, not cfg.live, "no sell route")
        lamports_out = int(quote.get("outAmount", 0))
        impact = _impact(quote)
        if not cfg.live:
            return ExecResult("sell", mint, True, True, "dry-run",
                              out_amount=lamports_out, price_impact_pct=impact)
        return self._execute_live("sell", mint, quote, out_amount=lamports_out,
                                  impact=impact)

    def _execute_live(self, action, mint, quote, *, sol_in=0.0, out_amount=0,
                      impact=None) -> ExecResult:
        cfg = self.config
        self._load_keypair()
        swap_b64 = jupiter.fetch_swap_transaction(
            quote, self._pubkey, base_url=cfg.jupiter_base,
            priority_lamports=cfg.priority_fee_lamports)
        if not swap_b64:
            return ExecResult(action, mint, False, False, "swap build failed",
                              sol_in=sol_in, out_amount=out_amount,
                              price_impact_pct=impact)

        sim = solana_rpc.simulate_transaction(swap_b64, cfg.rpc_url)
        if not sim.ok:
            return ExecResult(action, mint, False, False,
                              f"preflight sim failed: {sim.err}",
                              sol_in=sol_in, out_amount=out_amount,
                              price_impact_pct=impact)

        try:
            sig = self._sign_and_send(swap_b64)
        except Exception as e:  # network/signing failure
            return ExecResult(action, mint, False, False, f"send failed: {e}",
                              sol_in=sol_in, out_amount=out_amount,
                              price_impact_pct=impact)

        if cfg.confirm and not self._confirm(sig):
            # Unconfirmed: do NOT record a holding we may not actually own.
            return ExecResult(action, mint, False, False, "not confirmed in time",
                              sol_in=sol_in, out_amount=out_amount,
                              price_impact_pct=impact, signature=sig)

        if action == "buy":
            self.spent_sol += sol_in
        return ExecResult(action, mint, True, False, "confirmed", sol_in=sol_in,
                          out_amount=out_amount, price_impact_pct=impact, signature=sig)

    def _confirm(self, signature: str) -> bool:
        cfg = self.config
        deadline = time.monotonic() + cfg.confirm_timeout_s
        while time.monotonic() < deadline:
            try:
                st = solana_rpc.get_signature_status(signature, cfg.rpc_url)
            except http.SourceError:
                st = None
            if st and st.found:
                return st.confirmed and st.err is None
            time.sleep(cfg.confirm_poll_s)
        return False

    def pubkey(self) -> str:
        self._load_keypair()
        return self._pubkey or ""

    def token_balance(self, mint: str) -> int:
        return solana_rpc.get_token_balance(self.pubkey(), mint, self.config.rpc_url)

    def _sign_and_send(self, swap_b64: str) -> str:
        from solders.transaction import VersionedTransaction

        kp = self._load_keypair()
        raw = base64.b64decode(swap_b64)
        unsigned = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(unsigned.message, [kp])
        wire = base64.b64encode(bytes(signed)).decode()
        resp = http.post_json(self.config.rpc_url, {
            "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
            "params": [wire, {"encoding": "base64",
                              "skipPreflight": self.config.skip_preflight,
                              "maxRetries": 3}],
        })
        if isinstance(resp, dict) and resp.get("error"):
            raise RuntimeError(resp["error"])
        return (resp or {}).get("result", "")


def _impact(quote: dict) -> float | None:
    try:
        return float(quote.get("priceImpactPct"))
    except (TypeError, ValueError):
        return None
