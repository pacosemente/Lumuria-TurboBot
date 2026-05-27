#!/usr/bin/env python3
"""Sweep every trade configuration through the CRUEL market and report which,
if any, come out positive. Averages over several seeds so no single lucky run
fools us. Offline, no network.

    python3 sweep.py --tokens 2500
"""
from __future__ import annotations

import argparse
from statistics import mean

from lumuria import metrics
from lumuria.engine import Backtest
from lumuria.execution import PaperBroker
from lumuria.feeds import SimulatedFeed
from lumuria.safety import SafetyConfig, SafetyFilter
from lumuria.strategies import FixedStopTarget, ScaledExit, TrailingStop

POSITION_USD = 50.0


def configs():
    out = []
    # Fixed stop / take-profit target.
    for stop in (0.2, 0.3, 0.5):
        for target in (0.5, 1.0, 2.0, 4.0):
            out.append((f"fixed  stop{int(stop*100)} tgt{int(target*100)}",
                        (lambda s=stop, t=target: FixedStopTarget(s, t))))
    # Trailing stop.
    for stop in (0.3, 0.5):
        for arm in (0.2, 0.5):
            for trail in (0.25, 0.35, 0.5):
                out.append((f"trail  stop{int(stop*100)} arm{int(arm*100)} tr{int(trail*100)}",
                            (lambda s=stop, a=arm, tr=trail: TrailingStop(s, a, tr))))
    # Scaled: partial take + trail the rest.
    for first_t in (0.5, 1.0):
        for frac in (0.3, 0.5):
            for trail in (0.35, 0.5):
                out.append((f"scaled tgt{int(first_t*100)} take{int(frac*100)} tr{int(trail*100)}",
                            (lambda ft=first_t, fr=frac, tr=trail:
                             ScaledExit(0.30, ft, fr, tr))))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tokens", type=int, default=2500)
    ap.add_argument("--seeds", type=int, nargs="+", default=[7, 99, 2024, 555])
    ap.add_argument("--min-liquidity", type=float, nargs="+", default=[8_000, 30_000])
    args = ap.parse_args()

    # One cruel market per seed, reused across every config and filter.
    markets = {s: SimulatedFeed(n=args.tokens, seed=s, cruel=True).materialize()
               for s in args.seeds}
    broker = PaperBroker(fee_pct=0.015, slippage_pct=0.06, exit_slippage_pct=0.12,
                         priority_fee_usd=max(0.5, POSITION_USD * 0.01))
    cfgs = configs()

    print("=" * 70)
    print(f"  CRUEL-MODE SWEEP — {len(cfgs)} configs x {len(args.seeds)} seeds "
          f"x {args.tokens} tokens")
    print("=" * 70)

    for min_liq in args.min_liquidity:
        safety = SafetyFilter(SafetyConfig(min_liquidity_usd=min_liq))
        engine = Backtest(safety=safety, broker=broker, position_usd=POSITION_USD)

        rows = []
        for name, factory in cfgs:
            exps_r, exps_usd, n_trades = [], [], []
            for s in args.seeds:
                res = engine.run(markets[s], factory)
                m = metrics.compute(res.trades)
                exps_r.append(m.expectancy_r)
                exps_usd.append(m.expectancy_usd)
                n_trades.append(m.trades)
            rows.append((name, mean(exps_r), mean(exps_usd), mean(n_trades)))

        rows.sort(key=lambda r: r[1], reverse=True)
        positives = [r for r in rows if r[1] > 0]
        print(f"\n  --- selectivity: min liquidity ${min_liq:,.0f} "
              f"(~{rows[0][3]:.0f} trades/seed) ---")
        for name, exp_r, exp_usd, _ in rows:
            mark = "  <== POSITIVE" if exp_r > 0 else ""
            print(f"    {name:<28} {exp_r:+6.2f} R   ${exp_usd:+7.2f}/trade{mark}")
        print(f"    => {len(positives)} of {len(rows)} configs positive")

    print("\n" + "=" * 70)
    print("  Averaged over seeds; cruel assumptions live in feeds/simulated.py.")
    print("=" * 70)


if __name__ == "__main__":
    main()
