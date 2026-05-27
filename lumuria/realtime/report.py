"""Human-readable "complete vision" of a token plus its enter/skip verdict."""
from __future__ import annotations

from .decision import Category, Decision
from .view import TokenView


def _usd(v: float | None) -> str:
    return f"${v:,.0f}" if v is not None else "?"


def _pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "?"


def _flag(ok: bool | None, ok_txt: str, bad_txt: str) -> str:
    if ok is None:
        return "?  (unverified)"
    return f"OK   {ok_txt}" if ok else f"BAD  {bad_txt}"


def format_token(view: TokenView, decision: Decision) -> str:
    m = view.market
    a = view.authorities
    h = view.holders
    sq = view.sell_quote
    tx = view.tx

    lines: list[str] = []
    lines.append(f"  {view.symbol}  [{view.mint}]")
    if view.dex or view.name:
        lines.append(f"    {view.name}  on {view.dex}")
    lines.append(f"    price {('$' + format(m.price_usd, ',.8f')) if m.price_usd else '?'}"
                 f"  |  liquidity {_usd(m.liquidity_usd)}"
                 f"  |  FDV {_usd(m.fdv_usd)}"
                 f"  |  vol24h {_usd(m.volume_h24_usd)}")
    age = f"{m.age_minutes:.0f}m" if m.age_minutes is not None else "?"
    lines.append(f"    age {age}  |  buys/sells24h "
                 f"{m.buys_h24 if m.buys_h24 is not None else '?'}/"
                 f"{m.sells_h24 if m.sells_h24 is not None else '?'}")

    lines.append("    authorities:")
    lines.append(f"      freeze : {_flag(a.freeze_revoked if a.decimals is not None or a.freeze_authority else None, 'revoked', 'ACTIVE -> honeypot risk')}")
    lines.append(f"      mint   : {_flag(a.mint_revoked if a.decimals is not None or a.mint_authority else None, 'revoked', 'ACTIVE -> infinite-mint risk')}")

    lines.append(f"    LP locked/burned : {_pct(view.liquidity.lp_locked_or_burned_pct)}")
    lines.append(f"    holders : {h.count if h.count is not None else '?'}"
                 f"  |  top1 {_pct(h.top_holder_pct)}"
                 f"  |  top10 {_pct(h.top10_pct)}"
                 f"  |  insiders {_pct(h.insiders_pct)}")
    risks = ", ".join(view.risk.risks[:5]) if view.risk.risks else "-"
    lines.append(f"    RugCheck score : {view.risk.score if view.risk.score is not None else '?'}"
                 f"  |  rugged {view.risk.rugged}  |  risks: {risks}")

    route = "yes" if sq.route_exists else ("NO -> cannot exit" if sq.route_exists is False else "?")
    lines.append(f"    sell route : {route}  |  sell impact {_pct(sq.price_impact_pct)}")

    if tx:
        lines.append("    transaction value (round-trip simulated):")
        lines.append(f"      in {_usd(tx.position_usd)}  ->  back {_usd(sq.out_usd)}"
                     f"  |  buy impact {_pct(tx.buy_impact_pct)}"
                     f"  |  sell impact {_pct(tx.sell_impact_pct)}")
        lines.append(f"      round-trip cost {_pct(tx.est_roundtrip_cost_pct)}"
                     f"  (+ swap fee {tx.swap_fee_pct:.2%}, priority {_usd(tx.priority_fee_usd)})")

    if view.source_errors:
        errs = "; ".join(f"{k}: {v}" for k, v in view.source_errors.items())
        lines.append(f"    source errors : {errs}")

    lines.append(f"    VERDICT: {decision.summary}")
    for cat in Category:
        msgs = decision.by_category(cat)
        for msg in msgs:
            lines.append(f"      - [{cat.value}] {msg}")
    return "\n".join(lines)
