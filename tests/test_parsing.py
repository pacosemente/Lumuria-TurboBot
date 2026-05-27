"""Offline tests for the real-data parsers and the decision engine.

No network: every API response is a sample payload shaped like the real one,
so we can trust the parsing before pointing the bot at live endpoints.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.sources import dexscreener, geckoterminal, jupiter, rugcheck, solana_rpc
from lumuria.realtime.decision import Category, DecisionConfig, evaluate
from lumuria.realtime.view import (Authorities, Holders, Liquidity, Market,
                                   RiskReport, SellQuote, TokenView, TxEstimate)


# --------------------------------------------------------------------------
# Source parsers
# --------------------------------------------------------------------------

GECKO_NEW_POOLS = {
    "data": [{
        "id": "solana_POOL1", "type": "pool",
        "attributes": {
            "address": "POOL1", "name": "PEPE / SOL",
            "base_token_price_usd": "0.00000123", "reserve_in_usd": "45000.5",
            "fdv_usd": "120000", "pool_created_at": "2026-05-27T11:30:00Z",
            "volume_usd": {"h24": "23000"},
            "transactions": {"h24": {"buys": 120, "sells": 80}},
            "price_change_percentage": {"h1": "5.2"},
        },
        "relationships": {
            "base_token": {"data": {"id": "solana_MINT1"}},
            "dex": {"data": {"id": "raydium"}},
        },
    }]
}


def test_gecko_new_pools():
    pools = geckoterminal.parse_new_pools(GECKO_NEW_POOLS)
    assert len(pools) == 1
    p = pools[0]
    assert p["mint"] == "MINT1"
    assert p["pool_address"] == "POOL1"
    assert p["dex"] == "raydium"
    assert abs(p["market"].liquidity_usd - 45000.5) < 1e-6
    assert p["market"].buys_h24 == 120


DEXS_TOKEN = {
    "pairs": [
        {"chainId": "ethereum", "liquidity": {"usd": 999999}},  # must be ignored
        {"chainId": "solana", "dexId": "raydium", "priceUsd": "0.0000013",
         "liquidity": {"usd": 46000.0}, "fdv": 121000,
         "volume": {"h24": 24000},
         "txns": {"h24": {"buys": 121, "sells": 79}},
         "priceChange": {"h1": 5.1}, "pairCreatedAt": 1716800000000},
    ]
}


def test_dexscreener_picks_deepest_solana_pair():
    m = dexscreener.parse_token(DEXS_TOKEN)
    assert m is not None
    assert abs(m.liquidity_usd - 46000.0) < 1e-6
    assert m.buys_h24 == 121


def test_dexscreener_no_solana_pair():
    assert dexscreener.parse_token({"pairs": [{"chainId": "base"}]}) is None


RUGCHECK = {
    "score": 350, "rugged": False,
    "token": {"mintAuthority": None, "freezeAuthority": None, "decimals": 6},
    "topHolders": [{"pct": 12.5, "insider": False},
                   {"pct": 8.0, "insider": True},
                   {"pct": 3.0, "insider": False}],
    "markets": [{"lp": {"lpLockedPct": 100.0}}],
    "totalHolders": 540,
    "risks": [{"name": "Low amount of LP Providers"}],
}


def test_rugcheck_report():
    r = rugcheck.parse_report(RUGCHECK)
    assert r.score == 350
    assert r.mint_authority is None and r.freeze_authority is None
    assert abs(r.top_holder_pct - 0.125) < 1e-9
    assert abs(r.top10_pct - 0.235) < 1e-9
    assert abs(r.insiders_pct - 0.08) < 1e-9
    assert abs(r.lp_locked_pct - 1.0) < 1e-9
    assert r.holder_count == 540
    assert r.risks == ["Low amount of LP Providers"]


def test_solana_rpc_authorities():
    payload = {"result": {"value": {"data": {"parsed": {"info": {
        "mintAuthority": None, "freezeAuthority": "FREEZE1", "decimals": 9}}}}}}
    a = solana_rpc.parse_account_info(payload)
    assert a.freeze_authority == "FREEZE1"
    assert a.mint_authority is None
    assert a.decimals == 9
    assert not a.freeze_revoked and a.mint_revoked


TOKEN2022_MINT = {"result": {"value": {"data": {
    "program": "spl-token-2022",
    "parsed": {"info": {
        "decimals": 6, "mintAuthority": None, "freezeAuthority": None,
        "extensions": [
            {"extension": "transferFeeConfig",
             "state": {"newerTransferFee": {"transferFeeBasisPoints": 2000}}},
            {"extension": "defaultAccountState", "state": {"accountState": "frozen"}},
            {"extension": "transferHook", "state": {"programId": "HOOK1"}},
            {"extension": "permanentDelegate", "state": {"delegate": "DEL1"}},
        ],
    }},
}}}}


def test_token2022_extensions_parsed():
    a = solana_rpc.parse_account_info(TOKEN2022_MINT)
    assert a.program == "spl-token-2022"
    assert a.verified and a.decimals == 6
    assert a.default_account_frozen is True
    assert a.transfer_fee_bps == 2000
    assert abs(a.transfer_fee_pct - 0.20) < 1e-9
    assert a.has_transfer_hook is True
    assert a.has_permanent_delegate is True


def test_plain_spl_token_has_no_extensions():
    payload = {"result": {"value": {"data": {"program": "spl-token", "parsed": {
        "info": {"decimals": 9, "mintAuthority": None, "freezeAuthority": None}}}}}}
    a = solana_rpc.parse_account_info(payload)
    assert a.program == "spl-token"
    assert a.has_transfer_hook is False
    assert a.transfer_fee_bps is None


def test_jupiter_quote_ok_and_noroute():
    ok = jupiter.parse_quote({"outAmount": "49250000", "priceImpactPct": "0.0123"})
    assert ok.route_exists and ok.out_amount == 49250000
    assert abs(ok.price_impact_pct - 0.0123) < 1e-9
    assert not jupiter.parse_quote({"error": "No routes found"}).route_exists
    assert not jupiter.parse_quote({}).route_exists


# --------------------------------------------------------------------------
# Decision engine
# --------------------------------------------------------------------------

def _clean_view() -> TokenView:
    return TokenView(
        mint="MINT1", symbol="PEPE",
        market=Market(price_usd=1e-6, liquidity_usd=45000, fdv_usd=120000),
        authorities=Authorities(mint_authority=None, freeze_authority=None, decimals=6),
        holders=Holders(count=540, top_holder_pct=0.10, top10_pct=0.30, insiders_pct=0.05),
        liquidity=Liquidity(lp_locked_or_burned_pct=1.0),
        risk=RiskReport(score=200, rugged=False, risks=[]),
        sell_quote=SellQuote(route_exists=True, price_impact_pct=0.02, out_usd=48.0),
        tx=TxEstimate(position_usd=50, buy_impact_pct=0.02, sell_impact_pct=0.02,
                      est_roundtrip_cost_pct=0.05),
    )


CFG = DecisionConfig()


def test_clean_token_enters():
    d = evaluate(_clean_view(), CFG, position_usd=50)
    assert d.enter, d.reasons


def test_freeze_authority_is_honeypot():
    v = _clean_view()
    v.authorities.freeze_authority = "FREEZE1"
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.HONEYPOT)


def test_no_sell_route_is_honeypot():
    v = _clean_view()
    v.sell_quote.route_exists = False
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert any("sell route" in r for r in d.by_category(Category.HONEYPOT))


def test_mint_authority_is_scam():
    v = _clean_view()
    v.authorities.mint_authority = "MINTER"
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.SCAM)


def test_high_slippage_blocks():
    v = _clean_view()
    v.sell_quote.price_impact_pct = 0.30
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.SLIPPAGE)


def test_whale_concentration_blocks():
    v = _clean_view()
    v.holders.top_holder_pct = 0.55
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.SCAM)


def test_low_liquidity_blocks():
    v = _clean_view()
    v.market.liquidity_usd = 1500
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.LIQUIDITY)


def test_default_frozen_is_honeypot():
    v = _clean_view()
    v.authorities.program = "spl-token-2022"
    v.authorities.default_account_frozen = True
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert any("frozen" in r for r in d.by_category(Category.HONEYPOT))


def test_transfer_hook_is_honeypot():
    v = _clean_view()
    v.authorities.has_transfer_hook = True
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert any("hook" in r for r in d.by_category(Category.HONEYPOT))


def test_permanent_delegate_is_scam():
    v = _clean_view()
    v.authorities.has_permanent_delegate = True
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.SCAM)


def test_high_transfer_fee_is_scam():
    v = _clean_view()
    v.authorities.transfer_fee_bps = 2000  # 20%
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert any("transfer fee" in r for r in d.by_category(Category.SCAM))


def test_unverified_data_blocks_by_default():
    # Nothing known except a mint -> safety-first means skip.
    v = TokenView(mint="X")
    d = evaluate(v, CFG, position_usd=50)
    assert not d.enter
    assert d.by_category(Category.UNVERIFIED)


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
