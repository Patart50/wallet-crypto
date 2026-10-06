from decimal import Decimal

import pytest

from conftest import ADDR_BTC, ADDR_EVM, ADDR_HL, ADDR_SOL, d, fixture
from wallet_crypto.sources import HistoryCursor, MissingKey, SourceError, get_source
from wallet_crypto.sources.alchemy import (
    PORTFOLIO_URL,
    WCT_REWARD_DISTRIBUTOR,
    WCT_STAKE_WEIGHT,
    parse_locks,
    parse_token,
    parse_wct_transfers,
    raw_to_qty,
)
from wallet_crypto.sources.binance import eur_per_usd, parse_klines, parse_ticker, price_usd
from wallet_crypto.sources.hyperliquid import (
    API,
    load_market,
    paginate_by_time,
    parse_mode,
    parse_spot_pairs,
    parse_stake_history,
)
from wallet_crypto.sources.mempool import parse_address

# ---------------------------------------------------------------- Hyperliquid


def hl_routes(http, ch="hl_clearinghouse_unified.json", spot="hl_spot_unified.json", mode="unifiedAccount"):
    http.on_post(API, {"type": "userAbstraction"}, mode)
    http.on_post(API, {"type": "clearinghouseState"}, fixture(ch))
    http.on_post(API, {"type": "spotClearinghouseState"}, fixture(spot))
    http.on_post(API, {"type": "portfolio"}, fixture("hl_portfolio.json"))
    http.on_post(API, {"type": "userVaultEquities"}, fixture("hl_vaults.json"))
    http.on_post(API, {"type": "delegatorSummary"}, fixture("hl_delegator_summary.json"))
    return http


def test_hl_unified_no_double_counting(http):
    res = get_source("HL", hl_routes(http)).fetch_balances("HL:" + ADDR_HL)
    usdc = res.lines["USDC"]
    assert usdc.qty == d(1000) and usdc.val == d(1000)  # pas 1000 + 300
    assert usdc.extra["mode"] == "unified" and usdc.extra["transferable"] == d(700)
    assert usdc.extra["official_value"] == d("1374.5")
    assert "USDC_SPOT" not in res.lines
    assert res.lines["BTC"].qty == d("0.01")  # UBTC → BTC
    assert res.lines["USDT_SPOT"].val == d(20)
    assert "PURR" not in res.lines  # solde nul
    assert res.lines["HLP_VAULTS"].val == d("250.5")
    assert res.lines["HYPE_STAKED"].qty == d(115)
    (pos,) = res.positions
    assert pos["coin"] == "BTC" and pos["side"] == "LONG" and pos["roe"] == d(25) and pos["lev"] == 10
    assert all(p[1]["user"] == ADDR_HL for p in http.posts)  # préfixe « HL: » retiré


def test_hl_standard_account(http):
    hl_routes(http, "hl_clearinghouse_standard.json", "hl_spot_standard.json", mode="default")
    res = get_source("HL", http).fetch_balances(ADDR_HL, track_staking=False)
    assert res.lines["USDC"].qty == d("1500.25") and res.lines["USDC"].extra["mode"] == "standard"
    assert res.lines["USDC_SPOT"].qty == d(300)
    assert "HYPE_STAKED" not in res.lines
    assert res.positions[0]["side"] == "SHORT" and res.positions[0]["liq_px"] is None


def test_hl_unified_detected_by_heuristic(http):
    hl_routes(http, mode=RuntimeError("indisponible"))
    res = get_source("HL", http).fetch_balances(ADDR_HL)
    assert res.lines["USDC"].qty == d(1000)
    assert res.lines["USDC"].extra["account_mode"] == "unifiedaccount(heuristique)"


def test_hl_required_call_failure_raises(http):
    http.on_post(API, {"type": "userAbstraction"}, "default")
    http.on_post(API, {"type": "clearinghouseState"}, RuntimeError("timeout"))
    with pytest.raises(SourceError, match="clearinghouseState"):
        get_source("HL", http).fetch_balances(ADDR_HL)


def test_parse_mode():
    assert parse_mode("unifiedAccount") == "unifiedaccount"
    assert parse_mode({"abstraction": "portfolioMargin"}) == "portfoliomargin"
    assert parse_mode(None) == ""


def test_hl_history(http):
    fills = fixture("hl_fills.json")
    http.on_post(
        API,
        {"type": "userFillsByTime"},
        lambda p: [f for f in fills if p["startTime"] <= f["time"] <= p["endTime"]],
    )
    http.on_post(API, {"type": "userFunding"}, fixture("hl_funding.json"))
    http.on_post(API, {"type": "delegatorHistory"}, fixture("hl_delegator_history.json"))
    http.on_post(API, {"type": "delegatorRewards"}, fixture("hl_delegator_rewards.json"))
    b = get_source("HL", http).fetch_history(ADDR_HL, True, HistoryCursor())
    assert [f["tid"] for f in b.fills] == [101, 102, 103]
    assert b.fills[2]["is_spot"] and b.fills[1]["closed_pnl"] == d(100)
    assert isinstance(b.fills[0]["px"], Decimal)
    assert [x["usdc"] for x in b.funding] == [d("-0.42"), d("-0.40")]
    kinds = [e["kind"] for e in b.stake_events]
    assert kinds == [
        "DEPOSIT",
        "DELEG",
        "WITHDRAW_REQ",
        "WITHDRAW",
        "OTHER:linkStakingUse",
        "REWARD",
        "REWARD",
    ]
    assert len({e["ext_id"] for e in b.stake_events}) == len(b.stake_events)


def test_parse_stake_history_values():
    evs = parse_stake_history(ADDR_HL, fixture("hl_delegator_history.json"))
    assert evs[0]["qty"] == d(100) and evs[1]["detail"] == "0xval1"


def test_paginate_descending_batches():
    """Lots renvoyés du plus récent au plus ancien : on recule la fin."""
    data = list(range(1, 11))

    def fetch(st, en):
        sel = [x for x in data if st <= x <= en]
        return sorted(sel, reverse=True)[:4]

    out = paginate_by_time(fetch, lambda x: x, lambda x: x, 0, 100, page_limit=4)
    assert sorted(out) == data


def test_spot_pairs_and_market(http):
    pairs = parse_spot_pairs(fixture("hl_spot_meta.json"))
    assert pairs["@107"] == {"base": "HYPE", "raw": "HYPE", "quote": "USDC"}
    assert pairs["@142"]["base"] == "BTC"
    assert pairs["@500"]["quote"] == "BAR"
    http.on_post(API, {"type": "spotMeta"}, fixture("hl_spot_meta.json"))
    http.on_post(API, {"type": "allMids"}, RuntimeError("down"))
    p, mids = load_market(http)
    assert "@107" in p and mids == {}


# ---------------------------------------------------------------- Alchemy


def test_alchemy_requires_key(http):
    with pytest.raises(MissingKey, match="ALCHEMY_API_KEY"):
        get_source("EVM", http, "")


def test_raw_to_qty():
    assert raw_to_qty("0x0de0b6b3a7640000", 18) == 1
    assert raw_to_qty("2500000000", 9) == d("2.5")
    assert raw_to_qty("1.5", 18) == d("1.5")


def test_parse_token_native_without_metadata():
    t = fixture("alchemy_tokens_evm.json")["data"]["tokens"][0]
    assert parse_token(t) == ("ETH", d(1), d("3000.50"), "eth-mainnet")


def evm_routes(http, key="KEY1234567890", locks=None, claim="0x0", wct_fail=False):
    tokens = fixture("alchemy_tokens_evm.json")["data"]["tokens"]

    def portfolio(p):  # comme l'API : seulement les chaînes demandées dans l'appel
        nets = p["addresses"][0]["networks"]
        return {"data": {"tokens": [t for t in tokens if t["network"] in nets], "pageKey": None}}

    http.on_post(PORTFOLIO_URL.format(key=key), None, portfolio)

    def rpc(p):
        if wct_fail:
            raise RuntimeError("rpc down")
        if p["method"] == "eth_call":
            to = p["params"][0]["to"]
            return {"result": locks if to == WCT_STAKE_WEIGHT else claim}
        return {"result": {"transfers": []}}

    http.on_post("opt-mainnet.g.alchemy.com", None, rpc)
    return http


def lock_hex(amount_wei: int, end: int = 0, transferred: int = 0) -> str:
    def word(v):
        return format(v % 2**256, "064x")

    return "0x" + word(amount_wei) + word(end) + word(transferred)


def test_evm_balances_with_wct(http):
    locks = lock_hex(100 * 10**18, end=1800000000)
    claim = "0x" + format(5 * 10**18, "064x")
    res = get_source("EVM", evm_routes(http, locks=locks, claim=claim), "KEY1234567890").fetch_balances(
        ADDR_EVM
    )
    eth = res.lines["ETH"]
    assert eth.qty == d("1.5") and eth.val == d("1.5") * d("3000.50")
    assert eth.extra["chains"] == {"eth-mainnet": d(1), "arb-mainnet": d("0.5")}
    assert res.lines["USDC"].qty == d(500)
    assert res.lines["WCT"].val == d(15)
    assert "FREEAIRDROP.COM" not in res.lines and "DUST" not in res.lines
    assert res.warnings and "sans prix" in res.warnings[0]
    assert res.lines["WCT_STAKED"].qty == d(100) and res.lines["WCT_STAKED"].extra["lock_end"] == 1800000000
    assert res.lines["WCT_PENDING"].qty == d(5)


def test_evm_wct_failure_keeps_previous(http):
    res = get_source("EVM", evm_routes(http, wct_fail=True), "KEY1234567890").fetch_balances(ADDR_EVM)
    assert res.keep_previous == ("WCT_STAKED", "WCT_PENDING")
    assert "ETH" in res.lines and "WCT_STAKED" not in res.lines


def test_parse_locks_signed_and_short():
    amount, end, tr = parse_locks(lock_hex(-(10**18)))
    assert amount == d(-1) and end == 0 and tr == 0
    assert parse_locks("0x") == (0, 0, 0)


def test_wct_history(http):
    def rpc(p):
        q = p["params"][0]
        frm, to = q.get("fromAddress"), q.get("toAddress")

        def tr(uid, ts, val):
            return {
                "uniqueId": uid,
                "hash": "0x" + uid,
                "metadata": {"blockTimestamp": ts},
                "rawContract": {"value": hex(val), "decimal": "0x12"},
            }

        if to == WCT_STAKE_WEIGHT:
            return {"result": {"transfers": [tr("d1", "2026-01-01T00:00:00.000Z", 100 * 10**18)]}}
        if frm == WCT_STAKE_WEIGHT:
            return {"result": {"transfers": []}}
        if frm == WCT_REWARD_DISTRIBUTOR:
            return {"result": {"transfers": [tr("r1", "2026-01-08T00:00:00Z", 2 * 10**18)]}}
        raise AssertionError(q)

    http.on_post("opt-mainnet.g.alchemy.com", None, rpc)
    b = get_source("EVM", http, "K").fetch_history(ADDR_EVM, True, HistoryCursor())
    assert [(e["kind"], e["qty"]) for e in b.stake_events] == [("DEPOSIT", d(100)), ("REWARD", d(2))]
    assert b.stake_events[0]["time_ms"] == 1767225600000
    assert get_source("EVM", http, "K").fetch_history(ADDR_EVM, False, HistoryCursor()).stake_events == []


def test_wct_no_history_skips_other_calls(http):
    http.on_post("opt-mainnet.g.alchemy.com", None, {"result": {"transfers": []}})
    b = get_source("EVM", http, "K").fetch_history(ADDR_EVM, True, HistoryCursor())
    assert b.stake_events == [] and len(http.posts) == 1


def test_parse_wct_transfers_fallback_value():
    rows = parse_wct_transfers(
        ADDR_EVM, [{"hash": "0xh", "value": "3.5", "rawContract": {}, "metadata": {}}], "REWARD"
    )
    assert rows[0]["qty"] == d("3.5") and rows[0]["ext_id"] == "wct:0xh:REWARD"


def test_solana(http):
    http.on_post(PORTFOLIO_URL.format(key="K"), None, fixture("alchemy_tokens_sol.json"))
    res = get_source("SOL", http, "K").fetch_balances(ADDR_SOL)
    assert res.lines["SOL"].qty == d("2.5") and res.lines["SOL"].val == d(375)


# ---------------------------------------------------------------- Bitcoin, Binance


def test_mempool(http):
    assert parse_address(fixture("mempool_address.json")) == d("1.01")
    http.on_get("mempool.space", fixture("mempool_address.json"))
    res = get_source("BTC", http).fetch_balances(ADDR_BTC)
    assert res.lines["BTC"].qty == d("1.01") and res.lines["BTC"].val is None
    http2 = type(http)()
    http2.on_get("mempool.space", {"chain_stats": {}, "mempool_stats": {}})
    assert get_source("BTC", http2).fetch_balances(ADDR_BTC).lines == {}


def test_binance_prices():
    t = parse_ticker(fixture("binance_ticker.json"))
    assert "ZERO" not in t
    assert price_usd(t, "hype") == (d(41), "HYPEUSDT")
    assert price_usd(t, "BAR") == (d("2.5"), "BARUSDC")
    assert price_usd(t, "FOO") == (d("8.1"), "FOOBTC × BTCUSDT")
    assert price_usd(t, "NONE") == (None, "")
    assert eur_per_usd(t) == 1 / d("1.08")
    assert parse_klines([[1, "1", "2", "0.5", "1.5", "100"], ["bad"]]) == [(1, d("1.5"))]


def test_unknown_network(http):
    with pytest.raises(SourceError):
        get_source("TRON", http)
