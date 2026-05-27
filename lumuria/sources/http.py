"""Tiny stdlib HTTP client: JSON GET/POST with timeout, retries, backoff.

No third-party deps so the bot runs anywhere (including a bare VPS). External
data sources are flaky and rate-limited, so every call here is defensive.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "LumuriaTurboBot/0.1 (+https://github.com/pacosemente/Lumuria-TurboBot)"


class SourceError(RuntimeError):
    """A data source returned an error we can't recover from."""


class SourceUnavailable(SourceError):
    """The source could not be reached (network blocked, DNS, timeout)."""


def _request(
    url: str,
    *,
    method: str,
    data: bytes | None,
    headers: dict[str, str],
    timeout: float,
) -> Any:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw:
        return None
    return json.loads(raw)


def _with_retries(fn, *, retries: int, backoff: float):
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            # 4xx (except 429) won't fix itself; don't waste retries.
            if e.code != 429 and 400 <= e.code < 500:
                raise SourceError(f"HTTP {e.code} {e.reason}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        except json.JSONDecodeError as e:
            raise SourceError(f"invalid JSON from source: {e}") from e
        if attempt < retries:
            time.sleep(backoff * (2 ** attempt))
    raise SourceUnavailable(f"unreachable after {retries + 1} tries: {last}")


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    retries: int = 3,
    backoff: float = 1.5,
) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    return _with_retries(
        lambda: _request(url, method="GET", data=None, headers=hdrs, timeout=timeout),
        retries=retries,
        backoff=backoff,
    )


def post_json(
    url: str,
    payload: Any,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    retries: int = 3,
    backoff: float = 1.5,
) -> Any:
    body = json.dumps(payload).encode()
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        hdrs.update(headers)
    return _with_retries(
        lambda: _request(url, method="POST", data=body, headers=hdrs, timeout=timeout),
        retries=retries,
        backoff=backoff,
    )
