"""Tests for machine profiles: local / small / medium / large VPS."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria import profiles
from lumuria.profiles import PROFILES, Profile, detect, get


def test_all_profiles_exist_and_scale_up():
    for name in ("local", "small", "medium", "large"):
        assert isinstance(get(name), Profile)
    s, m, l = get("small"), get("medium"), get("large")
    assert s.tokens < m.tokens < l.tokens
    assert s.pop_size < m.pop_size < l.pop_size
    assert s.scan_interval > m.scan_interval > l.scan_interval  # bigger = faster


def test_detect_maps_resources_to_profiles():
    assert detect(cpus=1, ram_gb=1.0).name == "small"
    assert detect(cpus=2, ram_gb=4.0).name == "medium"
    assert detect(cpus=8, ram_gb=16.0).name == "large"
    assert detect(cpus=4, ram_gb=2.0).name == "small"  # RAM-starved big CPU


def test_auto_never_picks_local():
    assert get("auto").name in ("small", "medium", "large")
    assert get("").name in ("small", "medium", "large")


def test_unknown_profile_raises():
    try:
        get("gigantic")
    except ValueError as e:
        assert "gigantic" in str(e)
    else:
        raise AssertionError("expected ValueError for unknown profile")


def test_detect_uses_real_machine_without_args():
    assert detect().name in PROFILES
    assert profiles._ram_gb() > 0


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
