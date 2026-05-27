"""Offline tests for position sizing and the live paper trader's accounting."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.execution import PaperBroker
from lumuria.realtime.papertrade import LivePaperTrader
from lumuria.sizing import BankrollFractionSizer, FixedSizer, RampUpSizer
from lumuria.strategies import FixedStopTarget


# --- sizing ---------------------------------------------------------------

def test_fixed_sizer():
    s = FixedSizer(25)
    assert s.size(1000, 5) == 25
    assert s.size(10, 0) == 25


def test_bankroll_fraction_sizer():
    s = BankrollFractionSizer(fraction=0.10, min_usd=5)
    assert abs(s.size(1000, 0) - 100) < 1e-9
    assert s.size(10, 0) == 5  # floor kicks in


def test_rampup_grows_with_streak_and_caps():
    s = RampUpSizer(base=10, step=2.0, cap=50)
    assert s.size(1000, 0) == 10
    assert s.size(1000, 1) == 20
    assert s.size(1000, 2) == 40
    assert s.size(1000, 3) == 50  # capped, not 80


# --- live paper trader ----------------------------------------------------

def _trader(sizer=None):
    # Zero fee/slippage for exact arithmetic.
    return LivePaperTrader(
        broker=PaperBroker(fee_pct=0.0, slippage_pct=0.0),
        strategy_factory=lambda: FixedStopTarget(stop_pct=0.30, target_pct=1.00),
        sizer=sizer or FixedSizer(20),
        starting_bankroll=100.0,
    )


def test_open_deducts_bankroll():
    t = _trader()
    size = t.open_position("MINT", "AAA", price=1.0)
    assert size == 20
    assert abs(t.bankroll - 80.0) < 1e-9
    assert "MINT" in t.open
    # No double open of the same mint.
    assert t.open_position("MINT", "AAA", price=1.0) is None


def test_winning_trade_updates_bankroll_and_streak():
    t = _trader()
    t.open_position("MINT", "AAA", price=1.0)
    trade = t.tick("MINT", 2.0)  # +100% hits target
    assert trade is not None
    assert abs(trade.pnl_usd - 20.0) < 1e-9
    assert abs(t.bankroll - 120.0) < 1e-9
    assert t.wins_streak == 1
    assert abs(t.roi_pct - 0.20) < 1e-9


def test_losing_trade_resets_streak():
    t = _trader()
    t.wins_streak = 3
    t.open_position("MINT", "AAA", price=1.0)
    trade = t.tick("MINT", 0.7)  # -30% hits stop
    assert trade is not None
    assert trade.pnl_usd < 0
    assert t.wins_streak == 0


def test_rampup_scales_after_win():
    t = _trader(sizer=RampUpSizer(base=10, step=2.0, cap=100))
    assert t.open_position("M1", "AAA", 1.0) == 10  # streak 0
    t.tick("M1", 2.0)                                 # win -> streak 1
    assert t.wins_streak == 1
    assert t.open_position("M2", "BBB", 1.0) == 20    # bigger next time


def test_force_close_at_session_end():
    t = _trader()
    t.open_position("MINT", "AAA", price=1.0)
    trade = t.force_close("MINT", 1.5)
    assert trade is not None
    assert abs(trade.pnl_usd - 10.0) < 1e-9
    assert not t.open


def test_cannot_open_without_price_or_funds():
    t = _trader()
    assert t.open_position("M", "AAA", price=0.0) is None
    t.bankroll = 1.0
    assert t.open_position("M", "AAA", price=1.0) is None  # below min position


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
