"""Simulated data source for offline demos: turns the synthetic feed into
TokenViews the real decision engine can judge, and into a time-ordered market
whose prices evolve as a simulated clock advances.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..feeds.simulated import SimulatedFeed
from ..models import Fate, TokenLaunch
from .view import (Authorities, Holders, Liquidity, Market, RiskReport,
                   SellQuote, TokenView)


def synth_view(launch: TokenLaunch, position_usd: float,
               rng: random.Random) -> TokenView:
    """Derive a TokenView from a launch's hidden fate (with disguise noise), so
    the decision engine rejects bad tokens for realistic, specific reasons."""
    snap, fate = launch.snapshot, launch.fate
    liq = snap.liquidity_usd

    a = Authorities(decimals=6, program="spl-token", mint_authority=None,
                    freeze_authority=None, default_account_frozen=False,
                    has_transfer_hook=False, has_permanent_delegate=False,
                    transfer_fee_bps=0)
    sell_route = True

    if fate is Fate.HONEYPOT:
        trap = rng.choice(["freeze", "frozen", "hook", "noroute"])
        if trap == "freeze":
            a.freeze_authority = "Fz1111"
        elif trap == "frozen":
            a.program = "spl-token-2022"
            a.default_account_frozen = True
        elif trap == "hook":
            a.program = "spl-token-2022"
            a.has_transfer_hook = True
        else:
            sell_route = False
    elif fate is Fate.RUG and rng.random() < 0.6:
        a.mint_authority = "Mn1111"

    impact = min(position_usd / (liq / 2 + position_usd), 1.0) if liq else 1.0

    return TokenView(
        mint=snap.address, symbol=snap.symbol, dex="raydium",
        market=Market(price_usd=launch.path[0].price, liquidity_usd=liq,
                      fdv_usd=liq * 3, volume_h24_usd=liq * 0.5),
        authorities=a,
        holders=Holders(count=snap.holders, top_holder_pct=snap.top_holder_pct,
                        top10_pct=min(snap.top_holder_pct * 1.8, 1.0)),
        liquidity=Liquidity(lp_locked_or_burned_pct=1.0 if snap.lp_locked else 0.1),
        risk=RiskReport(score=200, rugged=False, risks=[]),
        sell_quote=SellQuote(route_exists=sell_route, price_impact_pct=impact),
    )


@dataclass
class TimedLaunch:
    launch_time: float  # simulated seconds since session start
    launch: TokenLaunch


class SimMarket:
    """A stream of token launches that arrive over (simulated) time."""

    def __init__(self, n: int, seed: int, cruel: bool,
                 arrivals_per_min: float = 6.0) -> None:
        self._rng = random.Random(seed)
        launches = SimulatedFeed(n=n, seed=seed, cruel=cruel).materialize()
        self.timed: list[TimedLaunch] = []
        t = 0.0
        mean_gap = 60.0 / max(arrivals_per_min, 0.1)
        for ln in launches:
            t += self._rng.expovariate(1.0 / mean_gap)
            self.timed.append(TimedLaunch(t, ln))
        self._next = 0

    def due(self, t_now: float) -> list[TokenLaunch]:
        out = []
        while self._next < len(self.timed) and self.timed[self._next].launch_time <= t_now:
            out.append(self.timed[self._next].launch)
            self._next += 1
        return out

    @property
    def exhausted(self) -> bool:
        return self._next >= len(self.timed)

    @staticmethod
    def price_at(launch: TokenLaunch, age: float) -> tuple[float, bool]:
        """Price `age` seconds after this token launched, and whether it's still
        alive (False once its path has run out — the token's life ended)."""
        path = launch.path
        price = path[0].price
        for tick in path:
            if tick.t <= age:
                price = tick.price
            else:
                return price, True
        return price, False
