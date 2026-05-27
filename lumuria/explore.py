"""Aggressive exploration: in the simulation the bot enters EVERY token on
purpose — including the losers — to learn what each kind of token actually
does. From that experience it reports, with data, what to avoid and how much
filtering each rule would improve results. This is explore-to-learn; live it
exploits the lesson by being selective.

Not consciousness — it is measured outcome analysis over deliberate mistakes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean

from .execution import PaperBroker
from .feeds import SimulatedFeed
from .models import Fate
from .realtime.simsource import synth_view
from .strategies import TrailingStop

POSITION_USD = 50.0


def _broker() -> PaperBroker:
    return PaperBroker(fee_pct=0.015, slippage_pct=0.06, exit_slippage_pct=0.12,
                       priority_fee_usd=max(0.5, POSITION_USD * 0.01))


def simulate_trade(launch, strategy, broker, size: float) -> float:
    pos = broker.buy_at_price(launch.snapshot.symbol, launch.path[0].price,
                              size, strategy.initial_risk_pct)
    can_sell = launch.fate is not Fate.HONEYPOT
    proceeds, last = 0.0, pos.entry_price
    for tick in launch.path[1:]:
        last = tick.price
        if not can_sell:
            continue
        for order in strategy.on_tick(pos, tick.price):
            proceeds += broker.sell(pos, tick.price, order.fraction)
        if pos.tokens <= 1e-12:
            break
    if pos.tokens > 1e-12:
        if can_sell:
            proceeds += broker.sell(pos, last, 1.0)
        else:
            pos.tokens = 0.0
    return proceeds - pos.cost_usd


def token_features(view) -> dict:
    """Observable features of a token, used both in sim study and live journal."""
    a = view.authorities
    return {
        "liquidity": view.market.liquidity_usd or 0.0,
        "holders": view.holders.count or 0,
        "top_holder": view.holders.top_holder_pct or 0.0,
        "lp_locked": (view.liquidity.lp_locked_or_burned_pct or 0.0) >= 0.8,
        "has_freeze": a.freeze_authority is not None,
        "has_mint_auth": a.mint_authority is not None,
        "t2022_trap": bool(a.default_account_frozen or a.has_transfer_hook),
        "no_sell_route": view.sell_quote.route_exists is False,
    }


def explore(seeds=(7, 99, 2024), tokens: int = 1500, *, stop: float = 0.30,
            arm: float = 0.20, trail: float = 0.25) -> list[dict]:
    broker = _broker()
    risk = POSITION_USD * stop
    records: list[dict] = []
    for s in seeds:
        rng = random.Random(s)
        for launch in SimulatedFeed(n=tokens, seed=s, cruel=True).stream():
            view = synth_view(launch, POSITION_USD, rng)
            pnl = simulate_trade(launch, TrailingStop(stop, arm, trail),
                                 broker, POSITION_USD)
            f = token_features(view)
            f.update(pnl=pnl, pnl_r=pnl / risk if risk else 0.0, win=pnl > 0)
            records.append(f)
    return records


def _stats(rows: list[dict]) -> tuple[int, float, float]:
    if not rows:
        return 0, 0.0, 0.0
    return len(rows), sum(r["win"] for r in rows) / len(rows), \
        mean(r["pnl_r"] for r in rows)


# Candidate "bad" segments to consider filtering out: (label, predicate, fix).
def _candidates():
    return [
        ("freeze authority", lambda r: r["has_freeze"], "keep BLOCKING it"),
        ("token-2022 trap", lambda r: r["t2022_trap"], "keep BLOCKING it"),
        ("no sell route", lambda r: r["no_sell_route"], "keep BLOCKING it"),
        ("mint authority active", lambda r: r["has_mint_auth"], "keep BLOCKING it"),
        ("LP not locked", lambda r: not r["lp_locked"], "require LP locked"),
        ("whale > 35%", lambda r: r["top_holder"] > 0.35, "tighten whale cap"),
        ("liquidity < $15k", lambda r: r["liquidity"] < 15_000, "raise min liquidity"),
        ("liquidity < $30k", lambda r: r["liquidity"] < 30_000, "raise min liquidity"),
        ("holders < 100", lambda r: r["holders"] < 100, "raise min holders"),
    ]


@dataclass
class Recommendation:
    label: str
    fix: str
    bad_n: int
    bad_win: float
    bad_r: float
    improvement_r: float  # expectancy gain from excluding this segment


def analyze(records: list[dict], *, min_sample: int = 25):
    n, win, base_r = _stats(records)
    segments = []
    recs: list[Recommendation] = []
    for label, pred, fix in _candidates():
        bad = [r for r in records if pred(r)]
        keep = [r for r in records if not pred(r)]
        bn, bwin, br = _stats(bad)
        segments.append((label, bn, bwin, br))
        if bn >= min_sample and keep:
            improvement = _stats(keep)[2] - base_r
            if improvement > 0.05:
                recs.append(Recommendation(label, fix, bn, bwin, br, improvement))
    recs.sort(key=lambda x: x.improvement_r, reverse=True)
    return {"n": n, "win": win, "base_r": base_r,
            "segments": segments, "recommendations": recs}
