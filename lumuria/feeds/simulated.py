"""Simulated Solana memecoin feed.

The model is deliberately pessimistic, matching what sniping really looks
like: most launches are scams or bleed to zero, and a small tail of winners
has to pay for all of them. The numbers below are rough, opinionated
estimates — tune them in one place and the whole simulation shifts.
"""
from __future__ import annotations

import random
from typing import Iterator

from ..models import Fate, PriceTick, TokenLaunch, TokenSnapshot

# Probability mass per fate. Must sum to 1.0.
FATE_WEIGHTS: dict[Fate, float] = {
    Fate.RUG: 0.34,
    Fate.HONEYPOT: 0.10,
    Fate.DUMP: 0.28,
    Fate.FLAT: 0.11,
    Fate.RUNNER: 0.14,
    Fate.MOONSHOT: 0.03,
}


class SimulatedFeed:
    def __init__(self, n: int = 500, seed: int | None = 42) -> None:
        self.n = n
        self._rng = random.Random(seed)

    def stream(self) -> Iterator[TokenLaunch]:
        for i in range(self.n):
            fate = self._pick_fate()
            snapshot = self._make_snapshot(i, fate)
            path = self._make_path(fate)
            yield TokenLaunch(snapshot=snapshot, path=path, fate=fate)

    def materialize(self) -> list[TokenLaunch]:
        """Return all launches as a list so several strategies can replay them."""
        return list(self.stream())

    # -- internals ---------------------------------------------------------

    def _pick_fate(self) -> Fate:
        fates = list(FATE_WEIGHTS.keys())
        weights = list(FATE_WEIGHTS.values())
        return self._rng.choices(fates, weights=weights, k=1)[0]

    def _make_snapshot(self, i: int, fate: Fate) -> TokenSnapshot:
        """Generate on-chain features correlated with fate, but noisy.

        Crucially, scams *disguise* themselves: a large share of rugs and
        honeypots fake locked LP and spread holders to look healthy, and some
        genuine projects launch looking sketchy. That overlap is why the safety
        filter is useful but far from a money printer — exactly like reality.
        """
        rng = self._rng
        scammy = fate in (Fate.RUG, Fate.HONEYPOT)
        healthy = fate in (Fate.RUNNER, Fate.MOONSHOT)

        if scammy:
            disguised = rng.random() < 0.45  # scam dressed up as legit
            if disguised:
                liquidity = rng.uniform(8_000, 60_000)
                holders = rng.randint(60, 800)
                top_holder = rng.uniform(0.05, 0.35)
                lp_locked = rng.random() < 0.75
                mint_renounced = rng.random() < 0.65
            else:
                liquidity = rng.uniform(500, 12_000)
                holders = rng.randint(5, 120)
                top_holder = rng.uniform(0.25, 0.85)
                lp_locked = rng.random() < 0.20
                mint_renounced = rng.random() < 0.25
        elif healthy:
            sketchy = rng.random() < 0.30  # good project, ugly launch optics
            if sketchy:
                liquidity = rng.uniform(2_000, 12_000)
                holders = rng.randint(20, 100)
                top_holder = rng.uniform(0.25, 0.50)
                lp_locked = rng.random() < 0.40
                mint_renounced = rng.random() < 0.40
            else:
                liquidity = rng.uniform(8_000, 120_000)
                holders = rng.randint(80, 1500)
                top_holder = rng.uniform(0.03, 0.30)
                lp_locked = rng.random() < 0.85
                mint_renounced = rng.random() < 0.80
        else:  # dump / flat: mediocre, mixed signals
            liquidity = rng.uniform(3_000, 40_000)
            holders = rng.randint(30, 600)
            top_holder = rng.uniform(0.10, 0.50)
            lp_locked = rng.random() < 0.55
            mint_renounced = rng.random() < 0.55

        return TokenSnapshot(
            symbol=f"TKN{i:04d}",
            address=f"sim{i:06d}{'x' * 32}",
            liquidity_usd=round(liquidity, 2),
            holders=holders,
            top_holder_pct=round(top_holder, 3),
            lp_locked=lp_locked,
            mint_renounced=mint_renounced,
        )

    def _make_path(self, fate: Fate) -> list[PriceTick]:
        rng = self._rng
        p = 1.0
        ticks = [PriceTick(0.0, p)]
        t = 0.0

        def step(dt: float, factor: float) -> None:
            nonlocal p, t
            t += dt
            p = max(p * factor, 1e-9)
            ticks.append(PriceTick(round(t, 1), p))

        if fate is Fate.HONEYPOT:
            # Looks alive for a moment, but a real exit is impossible.
            for _ in range(rng.randint(1, 3)):
                step(rng.uniform(2, 8), 1 + rng.uniform(0.0, 0.2))
            step(rng.uniform(2, 8), rng.uniform(0.0, 0.0001))

        elif fate is Fate.RUG:
            for _ in range(rng.randint(1, 6)):
                step(rng.uniform(3, 15), 1 + rng.uniform(-0.05, 0.25))
            step(rng.uniform(2, 10), rng.uniform(0.005, 0.04))  # liquidity yanked

        elif fate is Fate.DUMP:
            for _ in range(rng.randint(2, 5)):
                step(rng.uniform(5, 20), 1 + rng.uniform(0.05, 0.6))
            for _ in range(rng.randint(8, 20)):
                step(rng.uniform(10, 40), 1 + rng.uniform(-0.25, 0.02))

        elif fate is Fate.FLAT:
            for _ in range(rng.randint(15, 30)):
                step(rng.uniform(15, 60), 1 + rng.uniform(-0.08, 0.06))

        elif fate is Fate.RUNNER:
            target = rng.uniform(3.0, 20.0)
            climb = rng.randint(12, 30)
            per = target ** (1.0 / climb)
            for _ in range(climb):
                step(rng.uniform(10, 45), per * (1 + rng.uniform(-0.18, 0.18)))
            for _ in range(rng.randint(5, 15)):  # fade after the top
                step(rng.uniform(20, 60), 1 + rng.uniform(-0.2, 0.05))

        elif fate is Fate.MOONSHOT:
            target = rng.uniform(20.0, 200.0)
            climb = rng.randint(20, 45)
            per = target ** (1.0 / climb)
            for _ in range(climb):
                step(rng.uniform(10, 40), per * (1 + rng.uniform(-0.22, 0.22)))
            for _ in range(rng.randint(8, 20)):
                step(rng.uniform(20, 80), 1 + rng.uniform(-0.25, 0.05))

        return ticks
