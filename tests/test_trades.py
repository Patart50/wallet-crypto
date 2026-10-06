from decimal import Decimal

from conftest import d
from wallet_crypto.core.manual_trades import ManualTrade, ManualTradeTx, trade_position
from wallet_crypto.core.trades import build_hl_trades, chain_order, fill_fee, is_spot_coin, trade_stats


def f(tid, t, side, px, sz, start, pnl=0, fee="0", coin="BTC", **kw):
    return {
        "tid": tid,
        "coin": coin,
        "side": side,
        "px": d(px),
        "sz": d(sz),
        "start_position": d(start),
        "closed_pnl": d(pnl),
        "fee": d(fee),
        "fee_token": kw.get("fee_token", "USDC"),
        "builder_fee": d(kw.get("builder_fee", 0)),
        "time_ms": t,
        "dir": kw.get("dir", ""),
        "liquidation": kw.get("liquidation", False),
    }


def test_spot_and_fee():
    assert is_spot_coin("@107") and is_spot_coin("PURR/USDC") and not is_spot_coin("BTC")
    assert fill_fee({"fee": d(1), "fee_token": "USDC", "builder_fee": d("0.1")}) == d("1.1")
    assert fill_fee({"fee": d(1), "fee_token": "HYPE"}) == 0


def test_long_with_add_and_partial_close():
    fills = [
        f(1, 1000, "B", 100, 1, 0, fee="0.1"),
        f(2, 2000, "B", 110, 1, 1, fee="0.1"),
        f(3, 3000, "A", 120, 1, 2, pnl=15, fee="0.1"),
        f(4, 4000, "A", 130, 1, 1, pnl=25, fee="0.1"),
    ]
    funding = [
        {"time_ms": 2500, "coin": "BTC", "usdc": d("-0.5")},
        {"time_ms": 9000, "coin": "BTC", "usdc": d(-9)},
    ]
    (tr,) = build_hl_trades(fills, funding, now_ms=10_000)
    assert tr["side"] == "LONG" and tr["close_time"] == 4000
    assert tr["entry_px"] == d(105) and tr["exit_px"] == d(125)
    assert tr["closed_pnl"] == d(40) and tr["fees"] == d("0.4") and tr["funding"] == d("-0.5")
    assert tr["net"] == d("39.1")
    assert tr["size_max"] == d(2) and tr["n_fills"] == 4
    assert tr["ret_pct"] == d("39.1") / d(210) * 100


def test_reversal_splits_fill():
    fills = [
        f(1, 1000, "B", 100, 1, 0, fee="0.2"),
        f(2, 2000, "A", 90, 3, 1, pnl=-10, fee="0.6", dir="Long > Short"),
        f(3, 3000, "B", 80, 2, -2, pnl=20, fee="0.4"),
    ]
    short, long_ = build_hl_trades(fills)
    assert long_["side"] == "LONG" and long_["net"] == d(-10) - d("0.2") - d("0.2")
    assert short["side"] == "SHORT" and short["entry_px"] == d(90)
    assert short["fees"] == d("0.4") + d("0.4") and short["net"] == d(20) - d("0.8")


def test_chain_same_timestamp():
    a = f(30, 5, "B", 1, 1, 2)  # 2 → 3
    b = f(10, 5, "B", 1, 1, 0)  # 0 → 1 (tête)
    c = f(20, 5, "B", 1, 1, 1)  # 1 → 2
    assert [x["tid"] for x in chain_order([a, b, c])] == [10, 20, 30]


def test_incomplete_open_gap_liquidation():
    fills = [
        f(1, 1000, "A", 100, 1, 2, pnl=5),  # déjà ouvert avant l'historique
        f(2, 2000, "A", 100, 1, 1, pnl=5, liquidation=True),
        f(3, 3000, "B", 50, 1, 0, coin="ETH"),
        f(4, 4000, "B", 50, 1, 0, coin="ETH"),  # départ à 0 alors qu'ouvert : trou
        f(5, 5000, "B", 20, 1, 0, coin="SOL"),
        f(6, 5500, "B", 1, 1, 0, coin="@107"),  # spot ignoré
    ]
    trades = build_hl_trades(fills, now_ms=6000)
    by = {t["coin"]: t for t in trades if t["close_time"] is not None}
    assert by["BTC"]["incomplete"] and by["BTC"]["liquidated"] and by["BTC"]["side"] == "LONG"
    assert by["ETH"]["gap"]
    opens = [t for t in trades if t["close_time"] is None]
    assert {t["coin"] for t in opens} == {"ETH", "SOL"}
    sol = next(t for t in opens if t["coin"] == "SOL")
    assert sol["duration_min"] == Decimal(1000) / 60_000


def test_stats():
    trades = [
        {"close_time": 1, "net": d(30), "fees": d(1), "funding": d(0), "incomplete": False},
        {"close_time": 2, "net": d(-10), "fees": d(1), "funding": d(-1), "incomplete": True},
        {"close_time": 3, "net": d(-10), "fees": d(1), "funding": d(0), "incomplete": False},
        {"close_time": None, "net": d(100), "fees": d(0), "funding": d(0), "incomplete": False},
    ]
    s = trade_stats(trades)
    assert s["n"] == 3 and s["n_open"] == 1
    assert s["pf"] == d("1.5") and s["net"] == d(10) and s["expectancy"] == d(10) / 3
    assert s["wr"] == d(100) / 3
    assert s["avg_win"] == d(30) and s["avg_loss"] == d(-10)
    assert s["best"] == d(30) and s["worst"] == d(-10) and s["n_incomplete"] == 1
    assert trade_stats([{"close_time": 1, "net": d(5), "fees": 0, "funding": 0, "incomplete": False}])[
        "pf"
    ].is_infinite()
    assert trade_stats([])["wr"] is None


def test_manual_trade_leverage_and_override():
    tr = ManualTrade(1, "ETH", "SHORT", leverage=d(5))
    txs = [ManualTradeTx(1, "OPEN", d(2), d(3000)), ManualTradeTx(2, "REDUCE", d(1), d(2800))]
    m = trade_position(tr, txs, price_now=d(2900))
    assert m["realized"] == d(200)
    assert m["qty"] == d(1) and m["pmp"] == d(3000)
    assert m["margin"] == d(600) and m["latent"] == d(100)
    assert m["roe"] == d(100) / d(600) * 100
    tr.pnl_override = d(180)
    m2 = trade_position(tr, txs)
    assert m2["realized"] == d(180) and m2["realized_calc"] == d(200) and m2["latent"] is None
