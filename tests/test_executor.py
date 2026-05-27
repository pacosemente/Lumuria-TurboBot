"""Offline tests for the swap executor's dry-run logic and safety rails.

Network calls (Jupiter quotes) are monkeypatched, so no real requests happen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.execution import live_executor
from lumuria.execution.live_executor import ExecConfig, SwapExecutor
from lumuria.sources import jupiter

FAKE_QUOTE = {"outAmount": "49250000", "priceImpactPct": "0.0123"}


def _patch_quote(result):
    jupiter.fetch_quote_raw = lambda *a, **k: result  # type: ignore


def setup_function(_):
    _patch_quote(FAKE_QUOTE)


def test_dry_run_buy_sends_nothing():
    ex = SwapExecutor(ExecConfig(live=False, budget_sol=1.0, max_position_sol=0.05))
    r = ex.buy("MINT", 0.05)
    assert r.ok and r.dry_run
    assert r.sol_in == 0.05 and r.out_amount == 49250000
    assert ex.spent_sol == 0.0  # nothing actually spent in dry-run


def test_buy_clamped_to_max_position():
    ex = SwapExecutor(ExecConfig(live=False, max_position_sol=0.05, budget_sol=1.0))
    r = ex.buy("MINT", 0.50)
    assert r.sol_in == 0.05


def test_buy_rejected_over_budget():
    ex = SwapExecutor(ExecConfig(live=False, budget_sol=1.0, max_position_sol=5.0))
    r = ex.buy("MINT", 2.0)  # under per-trade cap but over remaining budget
    assert not r.ok
    assert "budget" in r.reason


def test_buy_no_route():
    _patch_quote(None)
    ex = SwapExecutor(ExecConfig(live=False))
    r = ex.buy("MINT", 0.05)
    assert not r.ok and r.reason == "no buy route"


def test_sell_no_route_flags_trap():
    _patch_quote(None)
    ex = SwapExecutor(ExecConfig(live=False))
    r = ex.sell("MINT", 1000)
    assert not r.ok and r.reason == "no sell route"


def test_live_without_keypair_errors_cleanly():
    _patch_quote(FAKE_QUOTE)
    ex = SwapExecutor(ExecConfig(live=True, keypair_path="/nonexistent/key.json"))
    # Should not raise out of buy(); it returns a failed ExecResult instead.
    try:
        r = ex.buy("MINT", 0.01)
        assert not r.ok
    except RuntimeError as e:
        assert "keypair" in str(e).lower()


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                setup_function(fn)
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
