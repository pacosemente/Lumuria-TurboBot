"""Offline tests for position persistence and the confirmation/balance parsers."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.realtime.store import PositionStore, StoredHolding
from lumuria.sources import solana_rpc


def _tmp() -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # start with no file
    return path


def test_save_and_load_roundtrip():
    path = _tmp()
    store = PositionStore(path)
    h = StoredHolding(mint="M1", symbol="AAA", sol_in=0.05, tokens=12345,
                      opened_ts=1.0, peak_value_sol=0.07, buy_sig="sig1")
    store.save({"M1": h})

    loaded = PositionStore(path).load()
    assert "M1" in loaded
    assert loaded["M1"] == h
    os.unlink(path)


def test_load_missing_file_is_empty():
    assert PositionStore("/nonexistent/path/xyz.json").load() == {}


def test_corrupt_file_recovers_to_empty():
    path = _tmp()
    with open(path, "w") as f:
        f.write("{ this is not valid json ]")
    store = PositionStore(path)
    assert store.load() == {}
    assert os.path.exists(path + ".corrupt")  # corrupt file preserved
    os.unlink(path + ".corrupt")


def test_put_and_remove_persist():
    path = _tmp()
    store = PositionStore(path)
    store.put(StoredHolding("M1", "AAA", 0.05, 1, 1.0))
    store.put(StoredHolding("M2", "BBB", 0.05, 2, 1.0))
    assert set(PositionStore(path).load()) == {"M1", "M2"}
    store.remove("M1")
    assert set(PositionStore(path).load()) == {"M2"}
    os.unlink(path)


def test_parse_signature_status():
    confirmed = {"result": {"value": [
        {"confirmationStatus": "confirmed", "err": None}]}}
    s = solana_rpc.parse_signature_status(confirmed)
    assert s.found and s.confirmed and s.err is None

    failed = {"result": {"value": [
        {"confirmationStatus": "confirmed", "err": {"InstructionError": [0, "x"]}}]}}
    s = solana_rpc.parse_signature_status(failed)
    assert s.found and not s.confirmed and s.err is not None

    missing = {"result": {"value": [None]}}
    s = solana_rpc.parse_signature_status(missing)
    assert not s.found and not s.confirmed


def test_parse_token_balance_sums_accounts():
    payload = {"result": {"value": [
        {"account": {"data": {"parsed": {"info": {
            "tokenAmount": {"amount": "1000"}}}}}},
        {"account": {"data": {"parsed": {"info": {
            "tokenAmount": {"amount": "2500"}}}}}},
    ]}}
    assert solana_rpc.parse_token_balance(payload) == 3500


def test_parse_token_balance_empty():
    assert solana_rpc.parse_token_balance({"result": {"value": []}}) == 0


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
