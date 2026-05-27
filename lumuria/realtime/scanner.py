"""Real-data scanner: discover every new Solana token, build a complete view
of it from all sources, and decide whether it's safe to (paper) enter.

In watch mode it keeps following each token so you see its whole life: when
liquidity collapses (a rug in progress) it flags it, and marks any paper
position closed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..sources import dexscreener, geckoterminal, jupiter, rugcheck, solana_rpc
from ..sources import http
from .decision import Decision, DecisionConfig, evaluate
from .view import Authorities, Market, TokenView, TxEstimate


@dataclass
class ScannerConfig:
    position_usd: float = 50.0
    rpc_url: str = solana_rpc.PUBLIC_RPC
    jupiter_base: str = jupiter.DEFAULT_BASE
    slippage_bps: int = 500
    swap_fee_pct: float = 0.0025
    priority_fee_usd: float = 0.05
    use_geckoterminal: bool = True
    use_dexscreener: bool = True
    use_rugcheck: bool = True
    use_rpc: bool = True
    use_jupiter: bool = True
    rug_liquidity_drop: float = 0.60  # drop from peak that flags a rug
    decision: DecisionConfig = field(default_factory=DecisionConfig)


@dataclass
class TrackedToken:
    mint: str
    symbol: str
    first_seen: float
    decision: Decision
    entered: bool
    peak_liquidity: float = 0.0
    last_liquidity: float = 0.0
    status: str = "watching"  # watching | entered | rugged | dead


def _merge_market(base: Market, other: Optional[Market]) -> Market:
    if other is None:
        return base
    for f in base.__dataclass_fields__:
        if getattr(base, f) is None and getattr(other, f) is not None:
            setattr(base, f, getattr(other, f))
    return base


class Scanner:
    def __init__(self, config: ScannerConfig | None = None) -> None:
        self.config = config or ScannerConfig()
        self.tracked: dict[str, TrackedToken] = {}

    # -- enrichment --------------------------------------------------------

    def enrich(
        self,
        mint: str,
        *,
        pool_address: str = "",
        name: str = "",
        dex: str = "",
        base_market: Optional[Market] = None,
    ) -> TokenView:
        c = self.config
        symbol = name.split("/")[0].strip() if name else "?"
        view = TokenView(mint=mint, symbol=symbol or "?", name=name,
                         pool_address=pool_address, dex=dex)
        view.market = base_market or Market()

        if c.use_dexscreener:
            self._safe(view, "dexscreener",
                       lambda: _merge_market(view.market,
                                             dexscreener.fetch_token_market(mint)))

        rpc_ok = False
        if c.use_rpc:
            def _rpc():
                nonlocal rpc_ok
                auth = solana_rpc.fetch_authorities(mint, c.rpc_url)
                view.authorities = auth
                rpc_ok = auth.decimals is not None
            self._safe(view, "rpc", _rpc)

        if c.use_rugcheck:
            self._safe(view, "rugcheck", lambda: self._apply_rugcheck(view, rpc_ok))

        if c.use_jupiter:
            self._safe(view, "jupiter", lambda: self._apply_jupiter(view))

        return view

    def _apply_rugcheck(self, view: TokenView, rpc_ok: bool) -> None:
        r = rugcheck.fetch_report(view.mint)
        view.risk.score = r.score
        view.risk.rugged = r.rugged
        view.risk.risks = r.risks
        view.holders.count = r.holder_count
        view.holders.top_holder_pct = r.top_holder_pct
        view.holders.top10_pct = r.top10_pct
        view.holders.insiders_pct = r.insiders_pct
        view.liquidity.lp_locked_or_burned_pct = r.lp_locked_pct
        if not rpc_ok:  # fall back to RugCheck's authority view
            view.authorities = Authorities(
                mint_authority=r.mint_authority,
                freeze_authority=r.freeze_authority,
                decimals=r.decimals,
            )

    def _apply_jupiter(self, view: TokenView) -> None:
        c = self.config
        rt = jupiter.roundtrip_usdc(view.mint, c.position_usd,
                                    slippage_bps=c.slippage_bps,
                                    base_url=c.jupiter_base)
        view.sell_quote.route_exists = rt.sell.route_exists
        view.sell_quote.price_impact_pct = rt.sell.price_impact_pct
        view.sell_quote.out_usd = rt.out_usd
        view.tx = TxEstimate(
            position_usd=c.position_usd,
            buy_impact_pct=rt.buy.price_impact_pct,
            sell_impact_pct=rt.sell.price_impact_pct,
            swap_fee_pct=c.swap_fee_pct,
            priority_fee_usd=c.priority_fee_usd,
            est_roundtrip_cost_pct=rt.roundtrip_cost_pct,
        )

    def _safe(self, view: TokenView, source: str, fn: Callable[[], object]) -> None:
        try:
            fn()
        except http.SourceError as e:
            view.source_errors[source] = str(e)
        except Exception as e:  # never let one source crash the scan
            view.source_errors[source] = f"{type(e).__name__}: {e}"

    def assess(self, view: TokenView) -> Decision:
        return evaluate(view, self.config.decision, self.config.position_usd)

    # -- scanning ----------------------------------------------------------

    def scan_once(self, *, page: int = 1) -> list[tuple[TokenView, Decision]]:
        pools: list[dict] = []
        if self.config.use_geckoterminal:
            pools = geckoterminal.fetch_new_pools(page=page)
        results: list[tuple[TokenView, Decision]] = []
        for p in pools:
            view = self.enrich(p["mint"], pool_address=p["pool_address"],
                               name=p["name"], dex=p["dex"],
                               base_market=p.get("market"))
            results.append((view, self.assess(view)))
        return results

    def watch(
        self,
        *,
        interval: float = 20.0,
        on_event: Callable[[str, TokenView, Decision], None],
        max_cycles: int | None = None,
    ) -> None:
        cycle = 0
        while max_cycles is None or cycle < max_cycles:
            cycle += 1
            for view, decision in self.scan_once():
                self._track(view, decision, on_event)
            time.sleep(interval)

    def _track(self, view, decision, on_event) -> None:
        liq = view.market.liquidity_usd or 0.0
        existing = self.tracked.get(view.mint)
        if existing is None:
            t = TrackedToken(
                mint=view.mint, symbol=view.symbol, first_seen=time.time(),
                decision=decision, entered=decision.enter,
                peak_liquidity=liq, last_liquidity=liq,
                status="entered" if decision.enter else "watching",
            )
            self.tracked[view.mint] = t
            on_event("ENTER" if decision.enter else "SEEN", view, decision)
            return

        existing.peak_liquidity = max(existing.peak_liquidity, liq)
        existing.last_liquidity = liq
        if existing.status not in ("rugged", "dead") and existing.peak_liquidity > 0:
            drop = 1 - liq / existing.peak_liquidity
            if drop >= self.config.rug_liquidity_drop:
                existing.status = "rugged"
                on_event("RUG", view, decision)
