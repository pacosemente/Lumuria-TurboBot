"""The "complete vision" of a token, assembled from every data source."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Market:
    """Price / liquidity / activity snapshot (GeckoTerminal + Dexscreener)."""

    price_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    fdv_usd: Optional[float] = None
    volume_h24_usd: Optional[float] = None
    age_minutes: Optional[float] = None
    buys_h24: Optional[int] = None
    sells_h24: Optional[int] = None
    price_change_h1_pct: Optional[float] = None


@dataclass
class Authorities:
    """Mint control + Token-2022 extensions, read straight from the chain.

    The strongest honeypot/rug signals on Solana live here:
      - freeze authority present     -> dev can freeze your account; can't sell
      - mint authority present       -> dev can mint unlimited supply and dump
      - default account state frozen -> you RECEIVE tokens frozen; can't sell
      - transfer hook                -> custom program runs on every transfer
                                        and can simply block your sell
      - permanent delegate           -> dev can move/burn your tokens any time
      - transfer fee                 -> a cut taken on every transfer (a high
                                        one is a soft honeypot)
    """

    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None
    decimals: Optional[int] = None
    program: Optional[str] = None  # "spl-token" | "spl-token-2022"
    default_account_frozen: Optional[bool] = None
    transfer_fee_bps: Optional[int] = None
    has_transfer_hook: Optional[bool] = None
    has_permanent_delegate: Optional[bool] = None

    @property
    def verified(self) -> bool:
        """True once we actually read the mint (decimals come back)."""
        return self.decimals is not None

    @property
    def mint_revoked(self) -> bool:
        return self.mint_authority is None

    @property
    def freeze_revoked(self) -> bool:
        return self.freeze_authority is None

    @property
    def transfer_fee_pct(self) -> Optional[float]:
        return self.transfer_fee_bps / 10_000 if self.transfer_fee_bps is not None else None


@dataclass
class Holders:
    count: Optional[int] = None
    top_holder_pct: Optional[float] = None   # 0-1
    top10_pct: Optional[float] = None         # 0-1
    insiders_pct: Optional[float] = None      # 0-1, bundled/insider supply


@dataclass
class Liquidity:
    lp_locked_or_burned_pct: Optional[float] = None  # 0-1


@dataclass
class RiskReport:
    """RugCheck aggregate."""

    score: Optional[int] = None              # higher = riskier (rugcheck scale)
    rugged: Optional[bool] = None
    risks: list[str] = field(default_factory=list)


@dataclass
class SellQuote:
    """Live Jupiter sell quote for the intended position size."""

    route_exists: Optional[bool] = None
    price_impact_pct: Optional[float] = None  # 0-1
    out_usd: Optional[float] = None


@dataclass
class TxEstimate:
    """What one round-trip actually costs at the chosen position size."""

    position_usd: float = 0.0
    buy_impact_pct: Optional[float] = None
    sell_impact_pct: Optional[float] = None
    swap_fee_pct: float = 0.0
    priority_fee_usd: float = 0.0
    est_roundtrip_cost_pct: Optional[float] = None  # total friction to get in & out


@dataclass
class TokenView:
    mint: str
    symbol: str = "?"
    name: str = ""
    pool_address: str = ""
    dex: str = ""

    market: Market = field(default_factory=Market)
    authorities: Authorities = field(default_factory=Authorities)
    holders: Holders = field(default_factory=Holders)
    liquidity: Liquidity = field(default_factory=Liquidity)
    risk: RiskReport = field(default_factory=RiskReport)
    sell_quote: SellQuote = field(default_factory=SellQuote)
    tx: Optional[TxEstimate] = None

    # Per-source error strings, so a missing source is visible, not silent.
    source_errors: dict[str, str] = field(default_factory=dict)
