"""Turn a complete TokenView into an ENTER / SKIP decision with reasons.

Safety-first: a token is entered only if every critical check passes *and*
the data needed to clear those checks actually came back. Missing critical
data counts against the token, not in its favor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .view import TokenView


class Category(str, Enum):
    HONEYPOT = "honeypot"
    SCAM = "scam"
    SLIPPAGE = "slippage"
    LIQUIDITY = "liquidity"
    UNVERIFIED = "unverified"


@dataclass
class DecisionConfig:
    min_liquidity_usd: float = 10_000.0
    max_slippage_pct: float = 0.10          # per-side and round-trip ceiling
    max_top_holder_pct: float = 0.20
    max_top10_pct: float = 0.60
    max_insiders_pct: float = 0.25
    max_rugcheck_score: int = 1500          # rugcheck "danger" territory
    require_freeze_revoked: bool = True     # freeze authority => honeypot
    require_mint_revoked: bool = True       # mint authority => infinite-mint rug
    require_lp_locked_pct: float = 0.80
    require_sell_route: bool = True
    block_on_unknown: bool = True           # unverified critical signal => skip
    # Token-2022 honeypot vectors:
    block_default_frozen: bool = True       # tokens arrive frozen => can't sell
    block_transfer_hook: bool = True        # custom program can block transfers
    block_permanent_delegate: bool = True   # dev can seize/burn your tokens
    max_transfer_fee_pct: float = 0.10      # tax taken on every transfer


@dataclass
class Reason:
    category: Category
    text: str


@dataclass
class Decision:
    enter: bool
    reasons: list[Reason] = field(default_factory=list)

    def by_category(self, cat: Category) -> list[str]:
        return [r.text for r in self.reasons if r.category == cat]

    @property
    def summary(self) -> str:
        if self.enter:
            return "ENTER"
        cats = sorted({r.category.value for r in self.reasons})
        return "SKIP (" + ", ".join(cats) + ")"


def estimate_impact_by_liquidity(position_usd: float, liquidity_usd: float | None):
    """Rough constant-product price impact: trade size vs. one pool side."""
    if not liquidity_usd or liquidity_usd <= 0:
        return None
    quote_reserve = liquidity_usd / 2.0
    return min(position_usd / (quote_reserve + position_usd), 1.0)


def evaluate(view: TokenView, config: DecisionConfig, position_usd: float) -> Decision:
    reasons: list[Reason] = []

    def block(cat: Category, text: str) -> None:
        reasons.append(Reason(cat, text))

    # --- liquidity --------------------------------------------------------
    liq = view.market.liquidity_usd
    if liq is None:
        if config.block_on_unknown:
            block(Category.UNVERIFIED, "liquidity unknown")
    elif liq < config.min_liquidity_usd:
        block(Category.LIQUIDITY, f"low liquidity (${liq:,.0f})")

    # --- honeypot: freeze authority + Token-2022 extensions --------------
    a = view.authorities
    if a.freeze_authority is not None:
        block(Category.HONEYPOT, "freeze authority active (can freeze your tokens)")
    elif not a.verified and config.block_on_unknown:
        block(Category.UNVERIFIED, "mint authorities unverified on-chain")

    if config.block_default_frozen and a.default_account_frozen:
        block(Category.HONEYPOT, "default account state frozen (arrives non-sellable)")
    if config.block_transfer_hook and a.has_transfer_hook:
        block(Category.HONEYPOT, "transfer hook program (can block your sell)")
    if config.block_permanent_delegate and a.has_permanent_delegate:
        block(Category.SCAM, "permanent delegate (dev can seize your tokens)")
    if a.transfer_fee_pct is not None and a.transfer_fee_pct > config.max_transfer_fee_pct:
        block(Category.SCAM, f"transfer fee {a.transfer_fee_pct:.0%} per trade")

    # --- honeypot: must have a sell route --------------------------------
    if config.require_sell_route:
        route = view.sell_quote.route_exists
        if route is False:
            block(Category.HONEYPOT, "no Jupiter sell route (cannot exit)")
        elif route is None and config.block_on_unknown:
            block(Category.UNVERIFIED, "sell route not verified")

    # --- rug: mint authority ---------------------------------------------
    if config.require_mint_revoked and view.authorities.mint_authority is not None:
        block(Category.SCAM, "mint authority active (infinite-mint risk)")

    # --- rug: LP lock -----------------------------------------------------
    lp = view.liquidity.lp_locked_or_burned_pct
    if lp is not None and lp < config.require_lp_locked_pct:
        block(Category.SCAM, f"LP only {lp:.0%} locked/burned")

    # --- scam: holder concentration --------------------------------------
    th = view.holders.top_holder_pct
    if th is not None and th > config.max_top_holder_pct:
        block(Category.SCAM, f"top holder owns {th:.0%}")
    t10 = view.holders.top10_pct
    if t10 is not None and t10 > config.max_top10_pct:
        block(Category.SCAM, f"top 10 own {t10:.0%}")
    ins = view.holders.insiders_pct
    if ins is not None and ins > config.max_insiders_pct:
        block(Category.SCAM, f"insiders hold {ins:.0%}")

    # --- scam: rugcheck verdict ------------------------------------------
    if view.risk.rugged:
        block(Category.SCAM, "RugCheck flags this as rugged")
    if view.risk.score is not None and view.risk.score > config.max_rugcheck_score:
        block(Category.SCAM, f"RugCheck risk score {view.risk.score}")

    # --- slippage: cross-confirmed ---------------------------------------
    sell_impact = view.sell_quote.price_impact_pct
    if sell_impact is not None and sell_impact > config.max_slippage_pct:
        block(Category.SLIPPAGE, f"Jupiter sell impact {sell_impact:.1%}")
    if view.tx and view.tx.est_roundtrip_cost_pct is not None \
            and view.tx.est_roundtrip_cost_pct > config.max_slippage_pct:
        block(Category.SLIPPAGE,
              f"round-trip cost {view.tx.est_roundtrip_cost_pct:.1%}")
    liq_impact = estimate_impact_by_liquidity(position_usd, liq)
    if liq_impact is not None and liq_impact > config.max_slippage_pct:
        block(Category.SLIPPAGE, f"liquidity-implied impact {liq_impact:.1%}")

    return Decision(enter=len(reasons) == 0, reasons=reasons)
