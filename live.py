#!/usr/bin/env python3
"""Operate live on REAL Solana data with a fixed SOL budget (default 1 SOL).

DRY-RUN by default: it scans, applies every safety gate (liquidity, honeypot
incl. Token-2022 traps, scam, slippage), and prints exactly which tokens it
WOULD buy and how the budget would be spent — sending nothing. This is the
safe way to watch it operate.

Real trading needs all of: --live  --keypair <path>  --i-understand-real-funds
The private key is read from that file on this machine and never transmitted
anywhere except to sign your own transactions.

Hardened for real operation: open positions are persisted to disk (survive a
restart), reconciled against on-chain balances in live mode, transactions are
confirmed before being recorded, and exits are monitored between scans.

Run on your VPS (the data APIs are blocked in the Claude sandbox):

    # safe preview, no money:
    python3 live.py --rpc-url https://your-rpc --budget-sol 1 --per-trade-sol 0.05
    # real (only after the preview looks right and a tiny manual test):
    python3 live.py --live --keypair ~/bot-key.json --i-understand-real-funds \
        --rpc-url https://your-rpc --budget-sol 1 --per-trade-sol 0.05
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from lumuria.execution.live_executor import ExecConfig, SwapExecutor, LAMPORTS_PER_SOL
from lumuria.notify import TelegramNotifier
from lumuria.realtime import Scanner, ScannerConfig
from lumuria.realtime.decision import DecisionConfig
from lumuria.realtime.store import PositionStore, StoredHolding
from lumuria.sources import http, jupiter, solana_rpc


def sell_value_sol(mint: str, tokens: int, base_url: str, slippage_bps: int) -> float | None:
    """Read-only: what would we get back in SOL right now (no send)."""
    q = jupiter.fetch_quote_raw(mint, jupiter.SOL, tokens,
                                slippage_bps=slippage_bps, base_url=base_url)
    if not q:
        return None
    return int(q.get("outAmount", 0)) / LAMPORTS_PER_SOL


def reconcile(holdings: dict[str, StoredHolding], execer: SwapExecutor,
              store: PositionStore) -> None:
    """In live mode, trust the chain over the file: drop anything we no longer
    actually hold, and correct token amounts that drifted."""
    changed = False
    for mint in list(holdings):
        try:
            bal = execer.token_balance(mint)
        except http.SourceError:
            continue  # can't check now; leave as-is
        if bal <= 0:
            print(f"[reconcile] dropping {holdings[mint].symbol} (chain balance 0)")
            del holdings[mint]
            changed = True
        elif bal != holdings[mint].tokens:
            holdings[mint].tokens = bal
            changed = True
    if changed:
        store.save(holdings)


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
    p.add_argument("--interval", type=float, default=25.0, help="seconds between new-token scans")
    p.add_argument("--exit-interval", type=float, default=5.0, help="seconds between exit checks")
    p.add_argument("--max-cycles", type=int, default=0)
    p.add_argument("--rpc-url", default="")
    p.add_argument("--state-file", default="lumuria_state.json")
    p.add_argument("--telegram-token", default="", help="overrides TELEGRAM_BOT_TOKEN")
    p.add_argument("--telegram-chat", default="", help="overrides TELEGRAM_CHAT_ID")
    p.add_argument("--status-every", type=int, default=20,
                   help="send a Telegram status every N scan cycles")
    args = p.parse_args()

    if args.live and not (args.keypair and args.i_understand_real_funds):
        print("Refusing --live without --keypair and --i-understand-real-funds.",
              file=sys.stderr)
        sys.exit(2)

    rpc = args.rpc_url or solana_rpc.PUBLIC_RPC
    slippage_bps = int(args.max_slippage * 10_000)
    scanner = Scanner(ScannerConfig(
        position_usd=args.per_trade_sol * 150,
        rpc_url=rpc, slippage_bps=slippage_bps,
        decision=DecisionConfig(min_liquidity_usd=args.min_liquidity,
                                max_slippage_pct=args.max_slippage),
    ))
    execer = SwapExecutor(ExecConfig(
        rpc_url=rpc, keypair_path=args.keypair, live=args.live,
        budget_sol=args.budget_sol, max_position_sol=args.per_trade_sol,
        slippage_bps=slippage_bps,
    ))
    store = PositionStore(args.state_file)
    holdings = store.load()
    notifier = TelegramNotifier(
        args.telegram_token or os.getenv("TELEGRAM_BOT_TOKEN", ""),
        args.telegram_chat or os.getenv("TELEGRAM_CHAT_ID", ""))

    if args.live:
        try:
            execer._load_keypair()  # fail fast on a bad/missing key file
        except RuntimeError as e:
            print(f"Cannot start live mode: {e}", file=sys.stderr)
            sys.exit(2)
        reconcile(holdings, execer, store)

    mode = "LIVE (real funds)" if args.live else "DRY-RUN (no money sent)"
    print("=" * 62)
    print(f"  LUMURIA TURBOBOT — live operation  [{mode}]")
    print(f"  budget {args.budget_sol} SOL | per trade {args.per_trade_sol} SOL "
          f"| TP x{args.take_profit} | SL x{args.stop}")
    if holdings:
        print(f"  resumed with {len(holdings)} open position(s) from {args.state_file}")
    print(f"  telegram: {'on' if notifier.enabled else 'off'}")
    print("=" * 62)
    notifier.startup(mode, args.budget_sol, args.per_trade_sol)

    realized_sol = 0.0
    scanned_total = skipped_total = 0

    def committed() -> float:
        return sum(h.sol_in for h in holdings.values())

    def manage_exits() -> None:
        nonlocal realized_sol
        for mint in list(holdings):
            h = holdings[mint]
            val = sell_value_sol(mint, h.tokens, jupiter.DEFAULT_BASE, slippage_bps)
            if val is None:
                print(f"[TRAP ] {h.symbol:<10} no sell route now (honeypot realized)")
                notifier.trap(h.symbol)
                continue
            h.peak_value_sol = max(h.peak_value_sol, val)
            if val >= args.take_profit * h.sol_in or val <= args.stop * h.sol_in:
                res = execer.sell(mint, h.tokens)
                if res.ok or res.dry_run:
                    got = res.out_amount / LAMPORTS_PER_SOL if res.ok else val
                    realized_sol += got
                    tag = "TP" if val >= args.take_profit * h.sol_in else "SL"
                    print(f"[SELL {tag}] {h.symbol:<10} {h.sol_in:.4f}->{got:.4f} SOL "
                          f"({got - h.sol_in:+.4f})  "
                          f"{res.signature or res.reason}")
                    notifier.sell(h.symbol, got - h.sol_in, tag, res.dry_run)
                    del holdings[mint]
                    store.save(holdings)
                else:
                    print(f"[SELL FAIL] {h.symbol:<10} {res.reason} (will retry)")

    def scan_for_entries() -> None:
        nonlocal scanned_total, skipped_total
        if committed() + args.per_trade_sol > args.budget_sol + 1e-9:
            return
        for view, decision in scanner.scan_once():
            scanned_total += 1
            if not decision.enter or view.mint in holdings:
                skipped_total += not decision.enter
                continue
            if committed() + args.per_trade_sol > args.budget_sol + 1e-9:
                break
            res = execer.buy(view.mint, args.per_trade_sol)
            if not (res.ok or res.dry_run):
                print(f"[skip ] {view.symbol:<10} {res.reason}")
                continue
            holdings[view.mint] = StoredHolding(
                mint=view.mint, symbol=view.symbol, sol_in=res.sol_in,
                tokens=res.out_amount, opened_ts=time.time(),
                peak_value_sol=res.sol_in, buy_sig=res.signature or "")
            store.save(holdings)
            tail = (res.signature or "sent") if not res.dry_run else "would buy"
            print(f"[BUY  ] {view.symbol:<10} {res.sol_in:.4f} SOL  "
                  f"impact {(res.price_impact_pct or 0):.1%}  liq "
                  f"${view.market.liquidity_usd or 0:,.0f}  {tail}")
            notifier.buy(view.symbol, res.sol_in,
                         view.market.liquidity_usd or 0, res.dry_run)

    cycle = 0
    try:
        while args.max_cycles == 0 or cycle < args.max_cycles:
            cycle += 1
            manage_exits()
            scan_for_entries()
            print(f"  cycle {cycle}: holding {len(holdings)}, committed "
                  f"{committed():.3f} SOL, realized {realized_sol:+.4f} SOL")
            if args.status_every and cycle % args.status_every == 0:
                notifier.status(args.budget_sol - committed() + realized_sol,
                                len(holdings), realized_sol,
                                scanned_total, skipped_total)
            # Keep watching exits at the faster cadence between scans.
            if args.max_cycles == 0 or cycle < args.max_cycles:
                waited = 0.0
                while waited < args.interval:
                    time.sleep(args.exit_interval)
                    waited += args.exit_interval
                    manage_exits()
    except http.SourceError as e:
        print(f"\n  Data source unreachable: {e}", file=sys.stderr)
        print("  Run on your VPS — these APIs are blocked in the sandbox.",
              file=sys.stderr)
        notifier.error(f"data source unreachable: {e}")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n  Stopped. Open positions saved to", args.state_file)

    notifier.shutdown(realized_sol, len(holdings))

    open_cost = committed()
    print("\n" + "-" * 62)
    print(f"  realized {realized_sol:.4f} SOL | still holding {len(holdings)} "
          f"({open_cost:.4f} SOL cost) | state in {args.state_file}")
    print("-" * 62)


if __name__ == "__main__":
    main()
