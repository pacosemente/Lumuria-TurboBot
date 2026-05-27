#!/usr/bin/env python3
"""Watch the bot operate in SIMULATED real time — a live dashboard, no network,
no money. Tokens arrive over a simulated clock; the real decision engine accepts
or rejects each one; accepted positions are held and their P&L updates live
until the trailing stop / target / rug exits them.

Uses the cruel market + the winning setup (selective entries + trailing stop).

    python3 simlive.py                 # watchable speed
    python3 simlive.py --tick-seconds 1.5   # slower, more lifelike
    python3 simlive.py --tick-seconds 0 --max-ticks 200   # instant (for logs)
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import deque

from lumuria.execution import PaperBroker
from lumuria.realtime.decision import DecisionConfig, evaluate
from lumuria.realtime.simsource import SimMarket, synth_view
from lumuria.strategies import TrailingStop

SOL_USD = 150.0


def fmt_clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start-sol", type=float, default=1.0)
    p.add_argument("--risk", type=float, default=0.04, help="bankroll fraction per trade")
    p.add_argument("--max-position-sol", type=float, default=0.1)
    p.add_argument("--max-open", type=int, default=20)
    p.add_argument("--min-liquidity", type=float, default=30_000.0)
    p.add_argument("--max-slippage", type=float, default=0.08)
    p.add_argument("--trail", type=float, default=0.25)
    p.add_argument("--arrivals", type=float, default=8.0, help="token launches per sim-minute")
    p.add_argument("--sim-step", type=float, default=20.0, help="sim seconds advanced per update")
    p.add_argument("--tick-seconds", type=float, default=0.6, help="wall-clock seconds per update")
    p.add_argument("--tokens", type=int, default=4000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--max-ticks", type=int, default=0, help="0 = until market dries up")
    args = p.parse_args()

    rng = random.Random(args.seed)
    market = SimMarket(n=args.tokens, seed=args.seed, cruel=True,
                       arrivals_per_min=args.arrivals)
    cfg = DecisionConfig(min_liquidity_usd=args.min_liquidity,
                         max_slippage_pct=args.max_slippage)
    broker = PaperBroker(fee_pct=0.015, slippage_pct=0.06, exit_slippage_pct=0.12,
                         priority_fee_usd=0.0005)
    position_usd = args.max_position_sol * SOL_USD

    bankroll = args.start_sol
    holdings: dict[str, dict] = {}
    events: deque[str] = deque(maxlen=8)
    realized = 0.0
    wins = trades = seen = 0
    skips = 0
    is_tty = sys.stdout.isatty()

    def log(msg: str) -> None:
        events.appendleft(msg)
        if not is_tty:
            print(msg)

    def render(sim_t: float) -> None:
        if not is_tty:
            return
        sys.stdout.write("\033[2J\033[H")  # clear + home
        roi = (bankroll + sum(h["sol_in"] for h in holdings.values())
               - args.start_sol) / args.start_sol * 100
        print("=" * 64)
        print(f"  LUMURIA TURBOBOT — SIMULATED LIVE      t=+{fmt_clock(sim_t)}")
        print("=" * 64)
        print(f"  bankroll {bankroll:.4f} SOL | open {len(holdings)}/{args.max_open} "
              f"| realized {realized:+.4f} SOL | ROI {roi:+.0f}%")
        print(f"  scanned {seen} | entered {trades} ({wins}W/{trades-wins}L) "
              f"| skipped {skips}")
        print("-" * 64)
        print("  OPEN POSITIONS")
        if not holdings:
            print("    (none)")
        for h in list(holdings.values())[:12]:
            now = (h["last_price"] / h["entry"] - 1) * 100
            peak = (h["pos"].peak_price / h["entry"] - 1) * 100
            print(f"    {h['symbol']:<10} in {h['sol_in']:.3f} SOL   "
                  f"now {now:+6.0f}%   peak {peak:+.0f}%")
        print("-" * 64)
        print("  RECENT")
        for e in events:
            print(f"    {e}")

    def close(mint: str, price: float, reason: str) -> None:
        nonlocal bankroll, realized, wins, trades
        h = holdings.pop(mint)
        pos = h["pos"]
        if pos.tokens > 1e-12:  # liquidate any remainder here, once
            proc = broker.sell(pos, price, 1.0)
            h["proceeds"] += proc
            bankroll += proc
        pnl = h["proceeds"] - h["sol_in"]
        realized += pnl
        trades += 1
        wins += pnl > 0
        tag = "win" if pnl > 0 else reason
        log(f"[SELL {tag}] {h['symbol']:<8} {pnl:+.4f} SOL")

    sim_t = prev_t = 0.0
    tick = 0
    try:
        while True:
            tick += 1
            prev_t, sim_t = sim_t, sim_t + args.sim_step

            # New launches arrive -> decide -> maybe buy.
            for launch in market.due(sim_t):
                seen += 1
                view = synth_view(launch, position_usd, rng)
                decision = evaluate(view, cfg, position_usd)
                if not decision.enter:
                    skips += 1
                    if decision.reasons:
                        log(f"[skip ] {view.symbol:<8} {decision.reasons[0].text[:34]}")
                    continue
                size = min(bankroll * args.risk, args.max_position_sol, bankroll)
                if len(holdings) >= args.max_open or size <= 1e-4:
                    continue
                strat = TrailingStop(0.30, 0.20, args.trail)
                entry = launch.path[0].price
                pos = broker.buy_at_price(view.symbol, entry, size, strat.initial_risk_pct)
                bankroll -= size
                holdings[view.mint] = {
                    "symbol": view.symbol, "pos": pos, "strat": strat,
                    "launch": launch, "launch_t": sim_t, "entry": pos.entry_price,
                    "sol_in": size, "last_price": pos.entry_price,
                    "proceeds": 0.0, "realized": 0.0,
                }
                log(f"[BUY  ] {view.symbol:<8} {size:.3f} SOL  liq "
                    f"${view.market.liquidity_usd:,.0f}")

            # Update held positions with their evolving price.
            for mint in list(holdings):
                h = holdings[mint]
                price, alive = SimMarket.price_at(h["launch"], sim_t - h["launch_t"])
                h["last_price"] = price
                pos = h["pos"]
                for order in h["strat"].on_tick(pos, price):
                    before = pos.tokens
                    proc = broker.sell(pos, price, order.fraction)
                    h["proceeds"] += proc
                    bankroll += proc
                if pos.tokens <= 1e-12:
                    close(mint, price, "exit")
                elif not alive:
                    close(mint, price, "died")  # close liquidates the remainder

            render(sim_t)
            if args.tick_seconds:
                time.sleep(args.tick_seconds)
            if (args.max_ticks and tick >= args.max_ticks) or \
                    (market.exhausted and not holdings):
                break
    except KeyboardInterrupt:
        pass

    print("\n" + "=" * 64)
    roi = (bankroll - args.start_sol) / args.start_sol * 100
    print(f"  SESSION END  t=+{fmt_clock(sim_t)}")
    print(f"  final bankroll {bankroll:.4f} SOL (start {args.start_sol}) | ROI {roi:+.0f}%")
    print(f"  entered {trades} ({wins}W/{trades-wins}L) | skipped {skips} | scanned {seen}")
    print("=" * 64)
    print("  Simulated — to see behavior, not a profit promise.")


if __name__ == "__main__":
    main()
