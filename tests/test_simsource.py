"""Tests for the simulated real-time source (synth views + timed market)."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.feeds.simulated import SimulatedFeed
from lumuria.models import Fate
from lumuria.realtime.decision import Category, DecisionConfig, evaluate
from lumuria.realtime.simsource import SimMarket, synth_view


def test_honeypot_fate_is_rejected():
    rng = random.Random(0)
    cfg = DecisionConfig(min_liquidity_usd=1)  # isolate the honeypot signal
    # Find a honeypot launch and confirm the engine rejects it.
    for launch in SimulatedFeed(n=400, seed=1, cruel=True).stream():
        if launch.fate is Fate.HONEYPOT:
            view = synth_view(launch, 50.0, rng)
            d = evaluate(view, cfg, 50.0)
            assert not d.enter
            assert d.by_category(Category.HONEYPOT) or d.by_category(Category.UNVERIFIED)
            return
    raise AssertionError("no honeypot generated to test")


def test_price_at_steps_and_ends():
    launch = next(SimulatedFeed(n=5, seed=2, cruel=True).stream())
    price0, alive0 = SimMarket.price_at(launch, 0.0)
    assert price0 == launch.path[0].price and alive0
    # Well past the last tick: the token's life has ended.
    _, alive_end = SimMarket.price_at(launch, launch.path[-1].t + 10_000)
    assert not alive_end


def test_market_arrivals_are_time_ordered():
    m = SimMarket(n=100, seed=3, cruel=True, arrivals_per_min=10)
    times = [tl.launch_time for tl in m.timed]
    assert times == sorted(times)
    early = m.due(times[0] + 0.001)
    assert len(early) >= 1


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
