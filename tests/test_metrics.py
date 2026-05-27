import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria import metrics
from lumuria.models import Fate, Trade


def _t(pnl_usd, pnl_r):
    return Trade("X", "s", Fate.DUMP, 1.0, 1.0, pnl_usd, pnl_r, "r")


def test_empty():
    m = metrics.compute([])
    assert m.trades == 0
    assert not m.is_profitable()


def test_positive_expectancy_with_low_win_rate():
    # 3 small losses, 1 big win -> the sniper profile. Should be profitable.
    trades = [_t(-50, -0.5), _t(-50, -0.5), _t(-50, -0.5), _t(400, 4.0)]
    m = metrics.compute(trades)
    assert m.trades == 4
    assert m.wins == 1 and m.losses == 3
    assert abs(m.win_rate - 0.25) < 1e-9
    assert m.total_pnl_usd == 250
    assert m.expectancy_usd == 62.5
    assert m.is_profitable()
    assert m.profit_factor == 400 / 150


def test_max_drawdown():
    # +100, -150, +20 -> peak 100, trough -50 -> drawdown 150
    m = metrics.compute([_t(100, 1), _t(-150, -1.5), _t(20, 0.2)])
    assert m.max_drawdown_usd == 150


def test_negative_expectancy():
    m = metrics.compute([_t(-50, -0.5), _t(-50, -0.5), _t(40, 0.4)])
    assert not m.is_profitable()


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
