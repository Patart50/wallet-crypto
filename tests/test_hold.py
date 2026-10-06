from conftest import d
from wallet_crypto.core.assets import AssetLine
from wallet_crypto.core.hold import HoldTx, build_hold_inputs, hold_position, spot_fill_tx
from wallet_crypto.core.staking import StakeEvent


def test_pmp_buy_sell():
    txs = [HoldTx(1, "BUY", d(1), d(100)), HoldTx(2, "BUY", d(1), d(200)), HoldTx(3, "SELL", d(1), d(300))]
    m = hold_position(d(1), txs, price_now=d(250))
    assert m.pmp == d(150)  # une vente ne change pas le PMP
    assert m.realized == d(150)
    assert m.latent == d(100) and m.value == d(250)
    assert [h["pmp_after"] for h in m.history] == [d(100), d(150), d(150)]


def test_fee_keeps_cost_raises_pmp():
    txs = [HoldTx(1, "BUY", d(10), d(10)), HoldTx(2, "FEE", d(2))]
    m = hold_position(d(8), txs)
    assert m.inv_qty == d(8) and m.pmp == d("12.5")
    assert m.realized == 0
    m2 = hold_position(d(0), [*txs, HoldTx(3, "FEE", d(8))])
    assert m2.inv_qty == 0 and m2.realized == d(-100)  # inventaire soldé : coût restant perdu


def test_staking_out_in_without_pnl():
    txs = [
        HoldTx(1, "BUY", d(10), d(10)),
        HoldTx(2, "OUT", d(4), src="staking"),
        HoldTx(3, "BUY", d(6), d(20)),
        HoldTx(4, "IN", d(4), src="staking"),
    ]
    m = hold_position(d(16), txs)
    # 6 à 10 € restent, 6 achetés à 20 € → PMP 15 ; puis 4 reviennent à 10 € → (180 + 40) / 16
    assert m.pmp == d(220) / d(16)
    assert m.realized == 0 and m.staked_cost_qty == 0


def test_coverage_rewards_unknown_excess_oversold():
    m = hold_position(d(15), [HoldTx(1, "BUY", d(10), d(1))], price_now=d(2), rewards_free=d(3))
    assert m.covered == d(10) and m.from_rewards == d(3) and m.unknown == d(2)
    assert m.coverage_pct == d(10) / d(15) * 100
    assert m.latent == d(10)  # seule la part au prix connu
    m2 = hold_position(d(5), [HoldTx(1, "BUY", d(10), d(1)), HoldTx(2, "SELL", d(12), d(2))])
    assert m2.oversold == d(2) and m2.inv_qty == 0
    m3 = hold_position(d(5), [HoldTx(1, "BUY", d(10), d(1))])
    assert m3.excess == d(5)


def test_same_timestamp_buy_before_sell():
    m = hold_position(d(0), [HoldTx(5, "SELL", d(1), d(20)), HoldTx(5, "BUY", d(1), d(10))])
    assert m.realized == d(10) and m.oversold == 0


def test_spot_fill_net_of_fees():
    pair = {"base": "HYPE", "raw": "HYPE", "quote": "USDC"}
    buy = spot_fill_tx(
        {"side": "B", "sz": d(10), "px": d(40), "fee": d("0.01"), "fee_token": "HYPE", "time_ms": 1}, pair
    )
    assert buy.kind == "BUY" and buy.qty == d("9.99") and buy.price == d(400) / d("9.99")
    sell = spot_fill_tx(
        {
            "side": "A",
            "sz": d(5),
            "px": d(50),
            "fee": d("0.2"),
            "fee_token": "USDC",
            "builder_fee": d("0.05"),
            "time_ms": 2,
        },
        pair,
    )
    assert sell.kind == "SELL" and sell.price == (d(250) - d("0.25")) / 5


def test_build_hold_inputs():
    wallets = [
        (
            "HL",
            "HL",
            {
                "HYPE": AssetLine("HYPE", d(10), px_sync=d(40)),
                "HYPE_STAKED": AssetLine("HYPE_STAKED", d(5)),
                "USDC": AssetLine("USDC", d(100), val=d(100)),
            },
        ),
        ("Ledger", "EVM", {"WCT": AssetLine("WCT", d(50), val=d(15))}),
    ]
    fills = [
        {
            "coin": "@107",
            "side": "B",
            "sz": d(10),
            "px": d(30),
            "fee": d(0),
            "fee_token": "USDC",
            "time_ms": 1,
        },
        {"coin": "@999", "side": "B", "sz": d(1), "px": d(1), "time_ms": 2},
    ]
    pairs = {"@107": {"base": "HYPE", "raw": "HYPE", "quote": "USDC"}}
    events = {
        ("HL_HYPE", "HYPE"): [StakeEvent(3, "DEPOSIT", d(5)), StakeEvent(4, "REWARD", d("0.1"))],
        ("WCT_OP", "WCT"): [StakeEvent(5, "REWARD", d(2), "x")],
    }
    hi = build_hold_inputs(wallets, [("wct", HoldTx(0, "BUY", d(40), d("0.2")))], fills, pairs, events)
    assert set(hi.real) == {"HYPE", "WCT"}  # le staké et les stables ne sont pas dans le hold
    assert hi.real["HYPE"]["qty"] == d(10)
    assert hi.prices == {"HYPE": d(40), "WCT": d("0.3")}
    assert hi.skipped_pairs == ["@999"]
    assert hi.n_src["HYPE"] == {"hl": 1, "man": 0} and hi.n_src["WCT"] == {"hl": 0, "man": 1}
    assert [t.kind for t in hi.txs["HYPE"]] == ["BUY", "OUT"]
    assert hi.rewards_free == {"HYPE": d(0), "WCT": d(2)}

    hi2 = build_hold_inputs(wallets, [], fills, pairs, events, pending={"WCT": d(1)}, include_staked=True)
    assert hi2.real["HYPE"]["qty"] == d(15) and hi2.real["HYPE"]["staked"] == d(5)
    assert [t.kind for t in hi2.txs["HYPE"]] == ["BUY"]  # passages internes ignorés
    assert hi2.rewards_free == {"HYPE": d("0.1"), "WCT": d(3)}
