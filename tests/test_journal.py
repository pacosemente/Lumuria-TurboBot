"""Offline tests for the trade journal and the performance report message."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.notify import TelegramNotifier
from lumuria.realtime.journal import TradeJournal
from lumuria.sources import http


def _tmp() -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.unlink(path)
    return path


def test_record_and_load_roundtrip():
    path = _tmp()
    j = TradeJournal(path)
    j.record("AAA", 0.05, 1.5, "TP")
    j.record("BBB", -0.02, -1.0, "SL")
    entries = j.load()
    assert len(entries) == 2
    assert entries[0].symbol == "AAA" and entries[0].pnl_sol == 0.05
    assert entries[1].reason == "SL"
    os.unlink(path)


def test_summary_computes_expectancy():
    path = _tmp()
    j = TradeJournal(path)
    # 3 small losses, 1 big win -> positive expectancy (the sniper profile).
    for _ in range(3):
        j.record("L", -0.02, -1.0, "SL")
    j.record("W", 0.20, 10.0, "TP")
    m = j.summary()
    assert m.trades == 4 and m.wins == 1
    assert m.is_profitable()
    assert abs(m.total_pnl_usd - 0.14) < 1e-9
    os.unlink(path)


def test_summary_window_limits_to_recent():
    path = _tmp()
    j = TradeJournal(path)
    for _ in range(10):
        j.record("L", -0.01, -1.0, "SL")
    for _ in range(3):
        j.record("W", 0.05, 5.0, "TP")
    assert j.summary().trades == 13
    assert j.summary(window=3).trades == 3
    assert j.summary(window=3).wins == 3  # only the recent winners
    os.unlink(path)


def test_corrupt_line_skipped():
    path = _tmp()
    with open(path, "w") as f:
        f.write('{"ts":1,"symbol":"A","pnl_sol":0.1,"pnl_r":1,"reason":"TP"}\n')
        f.write("garbage not json\n")
    assert len(TradeJournal(path).load()) == 1
    os.unlink(path)


def test_performance_message_profitable_and_trend():
    sent = []
    http.post_json = lambda url, payload, **k: sent.append(payload["text"])  # type: ignore
    n = TelegramNotifier("t", "1")

    path = _tmp()
    j = TradeJournal(path)
    for _ in range(8):
        j.record("L", -0.02, -1.0, "SL")
    for _ in range(4):
        j.record("W", 0.30, 12.0, "TP")
    n.performance(j.summary(), j.summary(window=6), realized_sol=0.96,
                  open_n=2, recent_window=6)
    msg = sent[-1]
    assert "PROFITABLE" in msg
    assert "win rate" in msg and "expectancy" in msg
    os.unlink(path)


def test_performance_message_no_trades():
    sent = []
    http.post_json = lambda url, payload, **k: sent.append(payload["text"])  # type: ignore
    n = TelegramNotifier("t", "1")
    path = _tmp()
    n.performance(TradeJournal(path).summary(), TradeJournal(path).summary(50),
                  0.0, 0, 50)
    assert "no closed trades yet" in sent[-1]


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
