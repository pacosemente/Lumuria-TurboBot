"""End-to-end integration test with the network mocked at the HTTP layer.

This exercises the REAL parsing and wiring of every component — discovery,
market enrichment, on-chain authorities, RugCheck, Jupiter quotes, the decision
engine and the dry-run executor — by faking only the lowest level (http.get_json
/ http.post_json). It proves the whole pipeline communicates correctly with
realistically-shaped data, without touching the network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lumuria.sources import http
from lumuria.execution.live_executor import ExecConfig, SwapExecutor
from lumuria.realtime import Scanner, ScannerConfig
from lumuria.realtime.decision import Category, DecisionConfig

CLEAN = "CLEANmint1111111111111111111111111111111111"
HONEY = "HONEYmint2222222222222222222222222222222222"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

NEW_POOLS = {"data": [
    {"attributes": {"address": "POOL_CLEAN", "name": "CLEAN / SOL",
                    "base_token_price_usd": "0.0001", "reserve_in_usd": "80000"},
     "relationships": {"base_token": {"data": {"id": f"solana_{CLEAN}"}},
                       "dex": {"data": {"id": "raydium"}}}},
    {"attributes": {"address": "POOL_HONEY", "name": "HONEY / SOL",
                    "base_token_price_usd": "0.0001", "reserve_in_usd": "60000"},
     "relationships": {"base_token": {"data": {"id": f"solana_{HONEY}"}},
                       "dex": {"data": {"id": "raydium"}}}},
]}


def fake_get_json(url, params=None, **kw):
    params = params or {}
    if "new_pools" in url:
        return NEW_POOLS
    if "dexscreener" in url:
        mint = url.rsplit("/", 1)[-1]
        liq = 80000 if mint == CLEAN else 60000
        return {"pairs": [{"chainId": "solana", "priceUsd": "0.0001",
                           "liquidity": {"usd": liq}, "fdv": liq * 3,
                           "volume": {"h24": liq}, "txns": {"h24": {"buys": 50, "sells": 40}}}]}
    if "rugcheck" in url:
        return {"score": 200, "rugged": False,
                "token": {"decimals": 6}, "totalHolders": 400,
                "topHolders": [{"pct": 8.0, "insider": False}],
                "markets": [{"lp": {"lpLockedPct": 100.0}}], "risks": []}
    if "quote" in url:  # jupiter
        # The honey token has no route back to USDC (sell side) -> trapped.
        if params.get("inputMint") == HONEY and params.get("outputMint") == USDC:
            return {"error": "no route"}
        return {"outAmount": str(int(params.get("amount", 0) * 0.95)),
                "priceImpactPct": "0.02"}
    raise AssertionError(f"unexpected GET {url}")


def fake_post_json(url, payload, **kw):
    method = payload.get("method")
    if method == "getAccountInfo":
        mint = payload["params"][0]
        info = {"decimals": 6, "mintAuthority": None, "freezeAuthority": None}
        if mint == HONEY:
            info["freezeAuthority"] = "FREEZE_AUTH"  # honeypot signal
        return {"result": {"value": {"data": {"program": "spl-token",
                                              "parsed": {"info": info}}}}}
    if method == "simulateTransaction":
        return {"result": {"value": {"err": None, "logs": []}}}
    if method == "getSignatureStatuses":
        return {"result": {"value": [{"confirmationStatus": "confirmed", "err": None}]}}
    if method == "getTokenAccountsByOwner":
        return {"result": {"value": [{"account": {"data": {"parsed": {"info": {
            "tokenAmount": {"amount": "1000000"}}}}}}]}}
    raise AssertionError(f"unexpected POST method {method}")


def setup_function(_):
    http.get_json = fake_get_json   # type: ignore
    http.post_json = fake_post_json  # type: ignore


def _scanner():
    return Scanner(ScannerConfig(
        position_usd=50.0,
        decision=DecisionConfig(min_liquidity_usd=15_000, max_slippage_pct=0.10),
    ))


def test_full_scan_clean_enters_honey_skips():
    results = {v.mint: (v, d) for v, d in _scanner().scan_once()}
    assert set(results) == {CLEAN, HONEY}

    clean_view, clean_dec = results[CLEAN]
    # Every source communicated: no errors, fields populated end to end.
    assert clean_view.source_errors == {}, clean_view.source_errors
    assert clean_view.market.liquidity_usd == 80000
    assert clean_view.authorities.verified
    assert clean_view.risk.score == 200
    assert clean_view.sell_quote.route_exists is True
    assert clean_dec.enter, clean_dec.reasons

    honey_view, honey_dec = results[HONEY]
    assert not honey_dec.enter
    assert honey_dec.by_category(Category.HONEYPOT)  # freeze authority + no sell route


def test_dry_run_executor_buys_clean():
    ex = SwapExecutor(ExecConfig(live=False, budget_sol=1.0, max_position_sol=0.05))
    r = ex.buy(CLEAN, 0.05)
    assert r.ok and r.dry_run and r.out_amount > 0


def test_enrichment_makes_expected_calls_without_error():
    # A single enrich should touch dexscreener, rpc, rugcheck and jupiter cleanly.
    view = _scanner().enrich(CLEAN)
    assert view.source_errors == {}
    assert view.market.liquidity_usd and view.authorities.decimals == 6
    assert view.tx is not None and view.tx.est_roundtrip_cost_pct is not None


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                setup_function(fn)
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
