"""Offline tests for adapting the brain from real trade data."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.adapt import adapt_brain
from lumuria.evolution import Genome


def _rec(liquidity, top_holder, holders, pnl_r):
    return {"liquidity": liquidity, "holders": holders, "top_holder": top_holder,
            "lp_locked": True, "has_freeze": False, "has_mint_auth": False,
            "t2022_trap": False, "no_sell_route": False,
            "pnl_r": pnl_r, "win": pnl_r > 0}


def test_no_records_no_change():
    g = Genome(8000, 50, 0.4, 0.3, 0.2, 0.25)
    new, changes = adapt_brain(g, [])
    assert new == g and changes == []


def test_tightens_liquidity_when_low_liq_loses():
    # Lots of losing low-liquidity trades + some winning high-liquidity ones.
    records = [_rec(8000, 0.2, 200, -1.5) for _ in range(40)]
    records += [_rec(80000, 0.2, 200, 3.0) for _ in range(15)]
    brain = Genome(min_liquidity=5000, min_holders=50, max_top_holder=0.4,
                   stop=0.3, arm=0.2, trail=0.25)
    new, changes = adapt_brain(brain, records, min_sample=20)
    assert new.min_liquidity >= 15000  # raised the floor
    assert any("min_liquidity" in c for c in changes)


def test_only_tightens_never_loosens():
    # Brain already strict; low-liq losers exist but threshold already above them.
    records = [_rec(8000, 0.2, 200, -1.5) for _ in range(40)]
    records += [_rec(80000, 0.2, 200, 3.0) for _ in range(20)]
    brain = Genome(min_liquidity=50000, min_holders=200, max_top_holder=0.2,
                   stop=0.3, arm=0.2, trail=0.25)
    new, _ = adapt_brain(brain, records, min_sample=20)
    assert new.min_liquidity >= 50000   # never lowered
    assert new.max_top_holder <= 0.2


def test_tightens_whale_cap():
    records = [_rec(80000, 0.5, 300, -1.4) for _ in range(40)]  # whales lose
    records += [_rec(80000, 0.1, 300, 2.0) for _ in range(40)]  # clean win
    brain = Genome(60000, 100, 0.45, 0.3, 0.2, 0.25)
    new, changes = adapt_brain(brain, records, min_sample=20)
    assert new.max_top_holder == 0.35
    assert any("max_top_holder" in c for c in changes)


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
