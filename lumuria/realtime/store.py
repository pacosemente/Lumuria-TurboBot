"""Persist open positions to disk so a restart never loses track of holdings.

A sniper bot that crashes mid-session must come back knowing exactly what it
holds, or it will either abandon bags or double-buy. State is written
atomically (temp file + rename) so a crash during a write can't corrupt it.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field


@dataclass
class StoredHolding:
    mint: str
    symbol: str
    sol_in: float
    tokens: int
    opened_ts: float
    peak_value_sol: float = 0.0
    buy_sig: str = ""
    features: dict | None = None  # token features at entry, for cross-analysis


@dataclass
class PositionStore:
    path: str
    _cache: dict[str, StoredHolding] = field(default_factory=dict)

    def load(self) -> dict[str, StoredHolding]:
        if not os.path.exists(self.path):
            self._cache = {}
            return {}
        try:
            with open(self.path) as f:
                raw = json.load(f)
            self._cache = {m: StoredHolding(**h) for m, h in raw.items()}
        except (json.JSONDecodeError, TypeError, ValueError, OSError):
            # Corrupt or unreadable: keep a backup, start clean rather than crash.
            try:
                os.replace(self.path, self.path + ".corrupt")
            except OSError:
                pass
            self._cache = {}
        return dict(self._cache)

    def save(self, holdings: dict[str, StoredHolding]) -> None:
        self._cache = dict(holdings)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({m: asdict(h) for m, h in holdings.items()}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic on POSIX

    def put(self, h: StoredHolding) -> None:
        self._cache[h.mint] = h
        self.save(self._cache)

    def remove(self, mint: str) -> None:
        self._cache.pop(mint, None)
        self.save(self._cache)
