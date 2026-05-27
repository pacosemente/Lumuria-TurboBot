"""Evolutionary optimisation: train the strategy in the cruel environment.

This is NOT consciousness or neural-network learning — it is a genetic
algorithm. A population of parameter sets (genomes: entry filters + trailing
exit) is scored by how much profit it survives with against the cruel market
across several seeds. The fittest breed, mutate, and over generations the
strategy adapts to overcome the harsh conditions. The best evolved genome is
saved as a "brain" the live bot can load.

Re-running this as real trades accumulate (folding the journal into the seeds)
is how the bot keeps evolving with the real market.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from statistics import mean

from .engine import Backtest
from .execution import PaperBroker
from .feeds import SimulatedFeed
from .metrics import compute
from .safety import SafetyConfig, SafetyFilter
from .strategies import TrailingStop

# gene -> (low, high, is_int)
BOUNDS = {
    "min_liquidity": (5_000.0, 120_000.0, False),
    "min_holders": (20, 1000, True),
    "max_top_holder": (0.10, 0.50, False),
    "stop": (0.15, 0.50, False),
    "arm": (0.10, 0.60, False),
    "trail": (0.15, 0.60, False),
}
POSITION_USD = 50.0


@dataclass
class Genome:
    min_liquidity: float
    min_holders: int
    max_top_holder: float
    stop: float
    arm: float
    trail: float

    def clamped(self) -> "Genome":
        d = asdict(self)
        for k, (lo, hi, is_int) in BOUNDS.items():
            v = min(max(d[k], lo), hi)
            d[k] = int(round(v)) if is_int else v
        return Genome(**d)


def random_genome(rng: random.Random) -> Genome:
    vals = {}
    for k, (lo, hi, is_int) in BOUNDS.items():
        v = rng.uniform(lo, hi)
        vals[k] = int(round(v)) if is_int else v
    return Genome(**vals)


def crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    da, db = asdict(a), asdict(b)
    return Genome(**{k: (da[k] if rng.random() < 0.5 else db[k]) for k in da})


def mutate(g: Genome, rng: random.Random, rate: float = 0.3) -> Genome:
    d = asdict(g)
    for k, (lo, hi, _) in BOUNDS.items():
        if rng.random() < rate:
            d[k] = d[k] + rng.gauss(0, (hi - lo) * 0.15)
    return Genome(**d).clamped()


def _broker() -> PaperBroker:
    return PaperBroker(fee_pct=0.015, slippage_pct=0.06, exit_slippage_pct=0.12,
                       priority_fee_usd=max(0.5, POSITION_USD * 0.01))


def _safety(g: Genome) -> SafetyFilter:
    return SafetyFilter(SafetyConfig(
        min_liquidity_usd=g.min_liquidity, min_holders=g.min_holders,
        max_top_holder_pct=g.max_top_holder, require_lp_locked=True))


def evaluate(g: Genome, markets: dict[int, list], *,
             min_total_trades: int = 60) -> tuple[float, float, int]:
    """Return (fitness, mean P&L, total trades) over the cruel markets."""
    broker = _broker()
    pnls, total_trades = [], 0
    for launches in markets.values():
        engine = Backtest(_safety(g), broker, POSITION_USD)
        res = engine.run(launches, lambda: TrailingStop(g.stop, g.arm, g.trail))
        m = compute(res.trades)
        pnls.append(m.total_pnl_usd)
        total_trades += m.trades
    mean_pnl = mean(pnls) if pnls else 0.0
    # A genome that barely trades isn't a strategy; force real volume.
    if total_trades < min_total_trades:
        return (-1e9 + total_trades, mean_pnl, total_trades)
    return (mean_pnl, mean_pnl, total_trades)


def _tournament(scored: list[tuple[float, Genome]], rng: random.Random,
                k: int = 3) -> Genome:
    return max(rng.sample(scored, min(k, len(scored))), key=lambda x: x[0])[1]


def evolve(*, generations: int = 12, pop_size: int = 24, seeds=(7, 99, 2024, 555),
           tokens: int = 1500, rng_seed: int = 0, min_total_trades: int = 60):
    """Run the GA. Returns (best_genome, best_fitness, history, best_detail)."""
    rng = random.Random(rng_seed)
    markets = {s: SimulatedFeed(n=tokens, seed=s, cruel=True).materialize()
               for s in seeds}
    pop = [random_genome(rng) for _ in range(pop_size)]
    elite = max(2, pop_size // 5)
    best: tuple[float, Genome] = (float("-inf"), pop[0])
    best_detail = (0.0, 0)
    history: list[float] = []

    for _ in range(generations):
        scored = []
        for g in pop:
            fit, pnl, n = evaluate(g, markets, min_total_trades=min_total_trades)
            scored.append((fit, g))
            if fit > best[0]:
                best, best_detail = (fit, g), (pnl, n)
        scored.sort(key=lambda x: x[0], reverse=True)
        history.append(scored[0][0])

        nxt = [g for _, g in scored[:elite]]
        while len(nxt) < pop_size:
            child = mutate(crossover(_tournament(scored, rng),
                                     _tournament(scored, rng), rng), rng)
            nxt.append(child)
        pop = nxt

    return best[1], best[0], history, best_detail


def save_brain(g: Genome, path: str, meta: dict | None = None) -> None:
    with open(path, "w") as f:
        json.dump({"genome": asdict(g), "meta": meta or {}}, f, indent=2)


def load_brain(path: str) -> Genome:
    with open(path) as f:
        return Genome(**json.load(f)["genome"]).clamped()
