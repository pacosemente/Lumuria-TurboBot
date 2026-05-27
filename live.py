#!/usr/bin/env python3
"""Operate live on REAL Solana data with a fixed SOL budget (default 1 SOL).

DRY-RUN by default: it scans, applies every safety gate (liquidity, honeypot
incl. Token-2022 traps, scam, slippage), and prints exactly which tokens it
WOULD buy and how the budget would be spent — sending nothing. This is the
safe way to watch it operate.

Real trading needs all of: --live  --keypair <path>  --i-understand-real-funds
The private key is read from that file on this machine and never transmitted
anywhere except to sign your own transactions.

Run on your VPS (the data APIs are blocked in the Claude sandbox):

    # safe preview, no money:
    python3 live.py --rpc-url https://your-rpc --budget-sol 1 --per-trade-sol 0.05
    # real (only after the preview looks right and a tiny manual test):
    python3 live.py --live --keypair ~/bot-key.json --i-understand-real-funds \
        --rpc-url https://your-rpc --budget-sol 1 --per-trade-sol 0.05
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

from lumuria.execution.live_executor import ExecConfig, SwapExecutor, LAMPORTS_PER_SOL
from lumuria.realtime import Scanner, ScannerConfig
from lumuria.realtime.decision import DecisionConfig
from lumuria.sources import http, jupiter, solana_rpc


@dataclass
class Holding:
    mint: str
    symbol: str
    sol_in: float
    tokens: int


def sell_value_sol(mint: str, tokens: int, base_url: str, slippage_bps: int) -> float | None:
    """Read-only: what would we get back in SOL right now (no send)."""
    q = jupiter.fetch_quote_raw(mint, jupiter.SOL, tokens,
                                slippage_bps=slippage_bps, base_url=base_url)
    if not q:
        return None
    return int(q.get("outAmount", 0)) / LAMPORTS_PER_SOL


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", action="store_true", help="actually send transactions")
    p.add_argument("--keypair", default="", help="path to Solana keypair json (live only)")
    p.add_argument("--i-understand-real-funds", action="store_true",
                   help="required acknowledgement for --live")
    p.add_argument("--budget-sol", type=float, default=1.0)
    p.add_argument("--per-trade-sol", type=float, default=0.05)
    p.add_argument("--take-profit", type=float, default=2.0, help="exit multiple, e.g. 2.0 = +100%%")
    p.add_argument("--stop", type=float, default=0.6, help="exit multiple, e.g. 0.6 = -40%%")
    p.add_argument("--min-liquidity", type=float, default=15_000.0)
    p.add_argument("--max-slippage", type=float, default=0.08)
    p.add_argument("--interval", type=float, default=25.0)
    p.add_argument("--max-cycles", type=int, default=0)
    p.add_argument("--rpc-url", default="")
    args = p.parse_args()

    if args.live and not (args.keypair and args.i_understand_real_funds):
        print("Refusing --live without --keypair and --i-understand-real-funds.",
              file=sys.stderr)
        sys.exit(2)

    rpc = args.rpc_url or solana_rpc.PUBLIC_RPC
    slippage_bps = int(args.max_slippage * 10_000)
    scanner = Scanner(ScannerConfig(
        position_usd=args.per_trade_sol * 150,  # rough USD for the slippage gate
        rpc_url=rpc, slippage_bps=slippage_bps,
        decision=DecisionConfig(min_liquidity_usd=args.min_liquidity,
                                max_slippage_pct=args.max_slippage),
    ))
    execer = SwapExecutor(ExecConfig(
        rpc_url=rpc, keypair_path=args.keypair, live=args.live,
        budget_sol=args.budget_sol, max_position_sol=args.per_trade_sol,
        slippage_bps=slippage_bps,
    ))

    if args.live:
        try:
            execer._load_keypair()  # fail fast on a bad/missing key file
        except RuntimeError as e:
            print(f"Cannot start live mode: {e}", file=sys.stderr)
            sys.exit(2)

    mode = "LIVE (real funds)" if args.live else "DRY-RUN (no money sent)"
    print("=" * 62)
    print(f"  LUMURIA TURBOBOT — live operation  [{mode}]")
    print(f"  budget {args.budget_sol} SOL | per trade {args.per_trade_sol} SOL "
          f"| TP x{args.take_profit} | SL x{args.stop}")
    print("=" * 62)

    holdings: dict[str, Holding] = {}
    committed_sol = 0.0
    realized_sol = 0.0
    cycle = 0
    try:
        while args.max_cycles == 0 or cycle < args.max_cycles:
            cycle += 1

            # 1) manage exits on what we hold
            for mint in list(holdings):
                h = holdings[mint]
                val = sell_value_sol(mint, h.tokens, jupiter.DEFAULT_BASE, slippage_bps)
                if val is None:  # lost the sell route => trapped; flag it
                    print(f"[TRAP ] {h.symbol:<10} no sell route now (honeypot realized)")
                    continue
                if val >= args.take_profit * h.sol_in or val <= args.stop * h.sol_in:
                    res = execer.sell(mint, h.tokens)
                    got = res.out_amount / LAMPORTS_PER_SOL if res.ok else val
                    realized_sol += got
                    pnl = got - h.sol_in
                    tag = "TP" if val >= args.take_profit * h.sol_in else "SL"
                    print(f"[SELL {tag}] {h.symbol:<10} {h.sol_in:.4f}->{got:.4f} SOL "
                          f"({pnl:+.4f})  {'sent '+ (res.signature or '') if res.ok and not res.dry_run else res.reason}")
                    del holdings[mint]

            # 2) look for new entries within budget
            if committed_sol + args.per_trade_sol <= args.budget_sol + 1e-9:
                for view, decision in scanner.scan_once():
                    if not decision.enter or view.mint in holdings:
                        continue
                    if committed_sol + args.per_trade_sol > args.budget_sol + 1e-9:
                        break
                    res = execer.buy(view.mint, args.per_trade_sol)
                    if not res.ok:
                        print(f"[skip ] {view.symbol:<10} {res.reason}")
                        continue
                    committed_sol += res.sol_in
                    holdings[view.mint] = Holding(view.mint, view.symbol,
                                                  res.sol_in, res.out_amount)
                    sent = (res.signature or "sent") if not res.dry_run else "would buy"
                    print(f"[BUY  ] {view.symbol:<10} {res.sol_in:.4f} SOL  "
                          f"impact {(res.price_impact_pct or 0):.1%}  liq "
                          f"${view.market.liquidity_usd or 0:,.0f}  {sent}")

            print(f"  cycle {cycle}: holding {len(holdings)}, committed "
                  f"{committed_sol:.3f} SOL, realized {realized_sol:+.4f} SOL")
            if args.max_cycles == 0 or cycle < args.max_cycles:
                time.sleep(args.interval)
    except http.SourceError as e:
        print(f"\n  Data source unreachable: {e}", file=sys.stderr)
        print("  Run on your VPS — these APIs are blocked in the sandbox.",
              file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n  Stopped.")

    open_cost = sum(h.sol_in for h in holdings.values())
    pnl = realized_sol - (committed_sol - open_cost)
    print("\n" + "-" * 62)
    print(f"  committed {committed_sol:.4f} SOL | realized {realized_sol:.4f} SOL "
          f"| still holding {len(holdings)} (${open_cost:.4f} SOL cost)")
    print(f"  realized P&L on closed trades: {pnl:+.4f} SOL")
    print("-" * 62)


if __name__ == "__main__":
    main()
