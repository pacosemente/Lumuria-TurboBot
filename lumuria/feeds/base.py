"""Feed interface: anything that emits new token launches.

A real Solana adapter (Raydium new-pool logs, pump.fun, Dexscreener) would
implement this same `stream()` method, so the engine never needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

from ..models import TokenLaunch


class PairFeed(ABC):
    @abstractmethod
    def stream(self) -> Iterator[TokenLaunch]:
        """Yield token launches one at a time."""
        raise NotImplementedError
