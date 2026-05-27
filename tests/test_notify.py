"""Offline tests for the Telegram notifier (network mocked)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria import notify
from lumuria.notify import TelegramNotifier, get_chat_ids
from lumuria.sources import http


def test_disabled_when_no_credentials():
    assert not TelegramNotifier("", "").enabled
    assert not TelegramNotifier("tok", "").enabled
    assert TelegramNotifier("tok", "123").enabled


def test_disabled_notifier_sends_nothing(monkeypatch=None):
    called = []
    http.post_json = lambda *a, **k: called.append(a)  # type: ignore
    n = TelegramNotifier("", "")
    assert n.send("hi") is False
    assert called == []


def test_send_posts_to_telegram_with_chat_and_text():
    captured = {}

    def fake_post(url, payload, **kw):
        captured["url"] = url
        captured["payload"] = payload
        return {"ok": True}

    http.post_json = fake_post  # type: ignore
    n = TelegramNotifier("BOTTOKEN", "999")
    assert n.send("hello world") is True
    assert "botBOTTOKEN/sendMessage" in captured["url"]
    assert captured["payload"] == {"chat_id": "999", "text": "hello world"}


def test_send_swallows_errors():
    def boom(*a, **k):
        raise http.SourceUnavailable("network down")

    http.post_json = boom  # type: ignore
    n = TelegramNotifier("t", "1")
    assert n.send("x") is False  # must not raise


def test_event_helpers_format_and_send():
    msgs = []
    http.post_json = lambda url, payload, **k: msgs.append(payload["text"])  # type: ignore
    n = TelegramNotifier("t", "1")
    n.buy("PEPE", 0.05, 42000, dry_run=True)
    n.sell("PEPE", 0.07, "TP", dry_run=False)
    n.trap("SCAM")
    assert any("PEPE" in m and "BUY" in m for m in msgs)
    assert any("PROFIT" in m and "+0.07" in m for m in msgs)
    assert any("TRAP" in m for m in msgs)


def test_get_chat_ids_parses_updates():
    payload = {"result": [
        {"message": {"chat": {"id": 111, "first_name": "Ana"}}},
        {"message": {"chat": {"id": 111, "first_name": "Ana"}}},  # dup
        {"channel_post": {"chat": {"id": -222, "title": "MyChan"}}},
    ]}
    http.get_json = lambda *a, **k: payload  # type: ignore
    ids = dict(get_chat_ids("tok"))
    assert ids == {"111": "Ana", "-222": "MyChan"}


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
