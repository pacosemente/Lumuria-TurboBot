"""Offline tests for the aggressive-exploration learner."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.explore import analyze, explore


def test_explore_enters_every_token():
    # No safety filter here: one trade record per simulated token.
    records = explore(seeds=(1,), tokens=300)
    assert len(records) == 300
    for r in records:
        assert "pnl_r" in r and "win" in r and "liquidity" in r


def test_analyze_flags_honeypot_segments_as_bad():
    records = explore(seeds=(1, 2), tokens=600)
    result = analyze(records, min_sample=5)
    seg = {label: (n, win, r) for label, n, win, r in result["segments"]}
    # Freeze authority / no sell route are catastrophic -> strongly negative R.
    if seg.get("freeze authority", (0,))[0] >= 5:
        assert seg["freeze authority"][2] < result["base_r"]
    if seg.get("no sell route", (0,))[0] >= 5:
        assert seg["no sell route"][2] < 0


def test_analyze_recommends_filters_that_improve_expectancy():
    result = analyze(explore(seeds=(1, 2, 3), tokens=800), min_sample=20)
    # Each recommendation must actually lift expectancy.
    for rec in result["recommendations"]:
        assert rec.improvement_r > 0
        assert rec.fix  # has actionable advice
    # Entering everything in the cruel market should not be profitable.
    assert result["base_r"] < 0


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
