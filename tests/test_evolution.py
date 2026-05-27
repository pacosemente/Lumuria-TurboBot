"""Offline tests for the evolutionary optimiser."""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.evolution import (BOUNDS, Genome, crossover, evolve, load_brain,
                               mutate, random_genome, save_brain)


def test_random_genome_within_bounds():
    rng = random.Random(0)
    for _ in range(50):
        g = random_genome(rng).__dict__
        for k, (lo, hi, _) in BOUNDS.items():
            assert lo <= g[k] <= hi


def test_clamp_pulls_into_bounds():
    g = Genome(min_liquidity=1e9, min_holders=-5, max_top_holder=2.0,
               stop=0.0, arm=5.0, trail=-1.0).clamped()
    assert g.min_liquidity == BOUNDS["min_liquidity"][1]
    assert g.min_holders == BOUNDS["min_holders"][0]
    assert g.max_top_holder == BOUNDS["max_top_holder"][1]
    assert g.trail == BOUNDS["trail"][0]


def test_mutate_and_crossover_stay_valid():
    rng = random.Random(1)
    a, b = random_genome(rng), random_genome(rng)
    child = mutate(crossover(a, b, rng), rng, rate=1.0)
    d = child.__dict__
    for k, (lo, hi, _) in BOUNDS.items():
        assert lo <= d[k] <= hi


def test_evolution_does_not_regress():
    # With elitism, the best fitness per generation must be non-decreasing.
    _, _, history, _ = evolve(generations=5, pop_size=6, seeds=(1, 2),
                              tokens=400, rng_seed=3, min_total_trades=0)
    assert all(history[i] <= history[i + 1] + 1e-9 for i in range(len(history) - 1))


def test_brain_save_load_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    g = Genome(30000, 100, 0.2, 0.3, 0.2, 0.35)
    save_brain(g, path, meta={"fitness": 1.0})
    loaded = load_brain(path)
    assert loaded == g.clamped()
    os.unlink(path)


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
