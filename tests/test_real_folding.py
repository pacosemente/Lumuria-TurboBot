"""Real trades steer evolution: the journal-folding path must be real code,
not a docstring promise."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.evolution import (Genome, entry_takes, evolve, real_fitness)


def _rec(liquidity, holders, top_holder, pnl_r):
    return {"liquidity": liquidity, "holders": holders, "top_holder": top_holder,
            "lp_locked": True, "has_freeze": False, "has_mint_auth": False,
            "t2022_trap": False, "no_sell_route": False,
            "pnl_r": pnl_r, "win": pnl_r > 0}


LOOSE = Genome(min_liquidity=5000, min_holders=20, max_top_holder=0.5,
               stop=0.3, arm=0.2, trail=0.25)
STRICT = Genome(min_liquidity=40000, min_holders=200, max_top_holder=0.2,
                stop=0.3, arm=0.2, trail=0.25)


def test_entry_takes_respects_every_entry_gene():
    good = _rec(50000, 300, 0.1, 1.0)
    assert entry_takes(STRICT, good)
    assert not entry_takes(STRICT, _rec(10000, 300, 0.1, 1.0))  # thin pool
    assert not entry_takes(STRICT, _rec(50000, 50, 0.1, 1.0))   # tiny crowd
    assert not entry_takes(STRICT, _rec(50000, 300, 0.4, 1.0))  # whale


def test_real_fitness_keeps_winners_and_dodges_losers():
    records = ([_rec(50000, 300, 0.1, 2.0)] * 3        # real winners, clean
               + [_rec(8000, 40, 0.45, -1.0)] * 5)     # real losers, sketchy
    loose_r, loose_n = real_fitness(LOOSE, records)
    strict_r, strict_n = real_fitness(STRICT, records)
    assert loose_n == 8 and abs(loose_r - 1.0) < 1e-9   # 6.0 won - 5.0 lost
    assert strict_n == 3 and abs(strict_r - 6.0) < 1e-9  # only the winners
    assert strict_r > loose_r  # dodging real losers must be worth something


def test_real_fitness_empty_when_genome_takes_nothing():
    r, n = real_fitness(STRICT, [_rec(6000, 30, 0.5, -1.0)] * 10)
    assert (r, n) == (0.0, 0)


def test_evolve_accepts_real_records_and_stays_monotonic():
    records = ([_rec(60000, 400, 0.1, 2.5)] * 15
               + [_rec(7000, 30, 0.45, -1.0)] * 15)
    _, _, history, _ = evolve(generations=4, pop_size=6, seeds=(1, 2),
                              tokens=300, rng_seed=3, min_total_trades=0,
                              real_records=records, min_real_sample=20)
    assert all(history[i] <= history[i + 1] + 1e-9 for i in range(len(history) - 1))


def test_small_journals_are_ignored_until_enough_evidence():
    few = [_rec(60000, 400, 0.1, 2.5)] * 5  # below min_real_sample
    a = evolve(generations=2, pop_size=4, seeds=(1,), tokens=200, rng_seed=7,
               min_total_trades=0, real_records=few, min_real_sample=20)
    b = evolve(generations=2, pop_size=4, seeds=(1,), tokens=200, rng_seed=7,
               min_total_trades=0, real_records=None)
    assert a[1] == b[1]  # identical run: tiny samples must not steer fitness


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
