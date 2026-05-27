#!/usr/bin/env python3
"""Real-data Solana token scanner.

Watches new tokens, builds a complete view from GeckoTerminal + Dexscreener +
RugCheck + Solana RPC + Jupiter, and decides ENTER / SKIP — refusing honeypots,
scams and tokens whose slippage is too high. No transactions are ever sent.

Needs outbound network to the data APIs. The Claude Code web sandbox blocks
them; run this on your VPS (free network, ideally with your own RPC):

    python3 scan.py --once
    python3 scan.py --mint <MINT_ADDRESS>
    python3 scan.py --watch --interval 20 --rpc-url https://your-rpc
"""
from __future__ import annotations

import argparse
import sys

from lumuria.realtime import Scanner, ScannerConfig, format_token
from lumuria.realtime.decision import DecisionConfig
from lumuria.sources import http, solana_rpc


def build_scanner(args) -> Scanner:
    decision = DecisionConfig(
        min_liquidity_usd=args.min_liquidity,
        max_slippage_pct=args.max_slippage,
    )
    cfg = ScannerConfig(
        position_usd=args.position_usd,
        rpc_url=args.rpc_url or solana_rpc.PUBLIC_RPC,
        slippage_bps=int(args.max_slippage * 10_000),
        decision=decision,
    )
    return Scanner(cfg)


def cmd_mint(scanner: Scanner, mint: str) -> None:
    view = scanner.enrich(mint)
    print(format_token(view, scanner.assess(view)))


def cmd_once(scanner: Scanner) -> None:
    results = scanner.scan_once()
    if not results:
        print("  No new pools returned (empty feed or network blocked).")
        return
    enters = 0
    for view, decision in results:
        print(format_token(view, decision))
        print()
        enters += decision.enter
    print(f"  {len(results)} tokens scanned, {enters} passed all safety gates.")


def cmd_watch(scanner: Scanner, interval: float) -> None:
    def on_event(kind, view, decision):
        tag = {"ENTER": "[ENTER]", "SEEN": "[skip ]",
               "RUG": "[RUG! ]"}.get(kind, f"[{kind}]")
        liq = view.market.liquidity_usd
        liq_s = f"${liq:,.0f}" if liq is not None else "?"
        print(f"{tag} {view.symbol:<12} liq {liq_s:>12}  {decision.summary}")

    print(f"  Watching new Solana tokens every {interval:.0f}s. Ctrl-C to stop.\n")
    scanner.watch(interval=interval, on_event=on_event)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mint", help="assess a single token by mint address")
    p.add_argument("--once", action="store_true", help="scan new pools once and exit")
    p.add_argument("--watch", action="store_true", help="continuously watch new tokens")
    p.add_argument("--interval", type=float, default=20.0)
    p.add_argument("--position-usd", type=float, default=50.0)
    p.add_argument("--min-liquidity", type=float, default=10_000.0)
    p.add_argument("--max-slippage", type=float, default=0.10,
                   help="max acceptable price impact / round-trip cost (fraction)")
    p.add_argument("--rpc-url", default="", help="your Solana RPC (recommended)")
    args = p.parse_args()

    scanner = build_scanner(args)
    try:
        if args.mint:
            cmd_mint(scanner, args.mint)
        elif args.watch:
            cmd_watch(scanner, args.interval)
        else:
            cmd_once(scanner)
    except http.SourceError as e:
        print(f"\n  Could not reach a data source: {e}", file=sys.stderr)
        print("  These APIs are blocked in the Claude web sandbox. Run on your VPS.",
              file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
