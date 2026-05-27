"""Sanity checks for the simulated feed (baseline vs cruel) and broker frictions."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.execution import PaperBroker
from lumuria.feeds.simulated import (CRUEL_FATE_WEIGHTS, FATE_WEIGHTS,
                                     SimulatedFeed)
from lumuria.models import Fate


def test_weights_sum_to_one():
    assert abs(sum(FATE_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(CRUEL_FATE_WEIGHTS.values()) - 1.0) < 1e-9


def test_cruel_has_more_scams_fewer_moonshots():
    assert CRUEL_FATE_WEIGHTS[Fate.RUG] > FATE_WEIGHTS[Fate.RUG]
    assert CRUEL_FATE_WEIGHTS[Fate.MOONSHOT] < FATE_WEIGHTS[Fate.MOONSHOT]


def test_feed_materializes_valid_launches():
    launches = SimulatedFeed(n=50, seed=1, cruel=True).materialize()
    assert len(launches) == 50
    for ln in launches:
        assert ln.path and ln.path[0].price == 1.0
        assert all(t.price > 0 for t in ln.path)


def test_exit_slippage_and_priority_fee_reduce_proceeds():
    cheap = PaperBroker(fee_pct=0.0, slippage_pct=0.0)
    cruel = PaperBroker(fee_pct=0.0, slippage_pct=0.0,
                        exit_slippage_pct=0.12, priority_fee_usd=1.0)
    pos_a = cheap.buy_at_price("X", 1.0, 100.0, 0.3)
    pos_b = cruel.buy_at_price("X", 1.0, 100.0, 0.3)
    assert cheap.sell(pos_a, 1.0, 1.0) > cruel.sell(pos_b, 1.0, 1.0)


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
