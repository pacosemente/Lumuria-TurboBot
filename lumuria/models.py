"""Core data structures shared across the bot."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Fate(str, Enum):
    """Ground-truth outcome of a token, used only by the simulator/analysis.

    A live bot never knows this in advance; it exists so we can measure how
    well the safety filter and exit strategies cope with each scenario.
    """

    RUG = "rug"            # liquidity pulled early, price -> ~0
    HONEYPOT = "honeypot"  # buyable but not sellable, effectively -100%
    DUMP = "dump"          # small pump then bleeds out
    FLAT = "flat"          # chops sideways, slow decline
    RUNNER = "runner"      # solid 3x-20x
    MOONSHOT = "moonshot"  # rare 20x-200x


@dataclass(frozen=True)
class PriceTick:
    t: float      # seconds since launch
    price: float  # price in quote units (normalized to ~1.0 at launch)


@dataclass(frozen=True)
class TokenSnapshot:
    """Features observable at (or shortly after) launch, fed to safety filters."""

    symbol: str
    address: str
    liquidity_usd: float
    holders: int
    top_holder_pct: float   # share held by the single largest wallet (0-1)
    lp_locked: bool
    mint_renounced: bool


@dataclass
class TokenLaunch:
    snapshot: TokenSnapshot
    path: list[PriceTick]
    fate: Fate  # ground truth, for analysis only


@dataclass
class Position:
    symbol: str
    entry_price: float
    tokens: float          # token units currently held
    cost_usd: float        # USD spent to acquire current holding (after fees)
    initial_tokens: float
    initial_risk_pct: float  # stop distance used to define one "R" for this trade
    peak_price: float = 0.0

    def __post_init__(self) -> None:
        self.peak_price = max(self.peak_price, self.entry_price)

    @property
    def remaining_fraction(self) -> float:
        return self.tokens / self.initial_tokens if self.initial_tokens else 0.0


@dataclass
class Trade:
    symbol: str
    strategy: str
    fate: Fate
    entry_price: float
    exit_price: float
    pnl_usd: float
    pnl_r: float
    reason: str


@dataclass
class SellOrder:
    fraction: float  # fraction of the *current* holding to sell (0-1)
    reason: str


@dataclass
class BacktestResult:
    strategy: str
    trades: list[Trade] = field(default_factory=list)
    skipped: int = 0           # launches rejected by the safety filter
    skipped_saved: int = 0     # of those, how many were rug/honeypot (good skips)
