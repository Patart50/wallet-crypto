from decimal import Decimal

from conftest import d
from wallet_crypto.core.assets import AssetLine, asset_base, asset_category, line_value
from wallet_crypto.core.portfolio import (
    ManualStakeItem,
    WalletAssets,
    auto_stake_bases,
    portfolio_summary,
    postes,
    wallet_kind,
)

PRICES = {"BTC": d(60000), "HYPE": d(40), "WCT": d("0.3"), "ETH": d(3000)}


def pf(base):
    return PRICES.get(base)


def test_asset_base_and_category():
    assert asset_base("WCT_STAKED") == "WCT"
    assert asset_base("usdc_spot") == "USDC"
    assert asset_base("HLP_VAULTS") == "USDC"
    assert asset_category("HYPE_STAKED") == "stake"
    assert asset_category("WCT_PENDING") == "stake"
    assert asset_category("HLP_VAULTS") == "stake"
    assert asset_category("USDT_SPOT") == "liquid"
    assert asset_category("BTC") == "hold"


def test_line_value_priority():
    # valeur de la source d'abord
    assert line_value(AssetLine("ETH", d(2), val=d(5000)), pf).value == d(5000)
    # stablecoin = 1
    assert line_value(AssetLine("USDC", d("12.5")), pf).value == d("12.5")
    # prix courant, puis prix de la sync, puis cache
    assert line_value(AssetLine("BTC", d("0.5")), pf).value == d(30000)
    assert line_value(AssetLine("XYZ", d(10), px_sync=d(2)), pf).value == d(20)
    assert line_value(AssetLine("XYZ", d(10)), pf, lambda b: d(3)).value == d(30)
    v = line_value(AssetLine("XYZ", d(10)), pf)
    assert v.unpriced and v.value == 0


def test_no_double_counting():
    """Le hold et le staking sont des vues des lignes réelles, jamais ajoutées en plus."""
    hl = WalletAssets(
        1,
        "HL principal",
        "HL",
        {
            "USDC": AssetLine("USDC", d(1000), val=d(1000)),
            "HYPE": AssetLine("HYPE", d(10)),
            "HYPE_STAKED": AssetLine("HYPE_STAKED", d(5)),
        },
        kind="manuel",
    )
    evm = WalletAssets(
        2,
        "Ledger",
        "EVM",
        {
            "ETH": AssetLine("ETH", d(1), val=d(3000)),
            "WCT_STAKED": AssetLine("WCT_STAKED", d(100)),
            "WCT_PENDING": AssetLine("WCT_PENDING", d(10)),
            "SCAM": AssetLine("SCAM", d(1000)),
        },
    )
    s = portfolio_summary([hl, evm], pf)
    assert s.liquid == d(1000)
    assert s.hold == d(400) + d(3000)
    assert s.stake == d(200) + d(30) + d(3)
    assert s.total == s.liquid + s.hold + s.stake
    assert s.unpriced == ["Ledger:SCAM"]
    assert s.by_wallet[1] == d(1600)
    assert s.by_wallet_cat[2]["stake"] == d(33)
    assert s.by_coin["HYPE"]["qty"] == d(10) and "HYPE_STAKED" in s.by_coin
    assert auto_stake_bases([hl, evm]) == {"HYPE", "WCT"}


def test_manual_stake_duplicate_excluded():
    w = WalletAssets(1, "HL", "HL", {"HYPE_STAKED": AssetLine("HYPE_STAKED", d(5))})
    items = [
        ManualStakeItem(1, "HYPE", d(5), d(200), duplicate=True),
        ManualStakeItem(2, "DOT", d(10), d(50)),
        ManualStakeItem(3, "ATOM", d(1), None),
    ]
    s = portfolio_summary([w], pf, manual_items=items)
    assert s.manual == d(50)
    assert s.duplicates == ["HYPE"]
    assert "staking manuel:ATOM" in s.unpriced
    assert s.total == d(200) + d(50)


def test_wallet_kind_and_postes():
    assert wallet_kind("HL", True) == "auto"
    assert wallet_kind("HL", False) == "manuel"
    assert wallet_kind("EVM", True) == "autres"
    p = postes(
        liquid=d(1500),
        hold=d(100),
        stake=d(50),
        manual=d(10),
        by_wallet_cat={"1": {"liquid": d(1000)}, "2": {"liquid": d(400)}, "3": {"liquid": d(100)}},
        kinds={"1": "auto", "2": "manuel", "3": "autres"},
    )
    assert p == {"stake": d(60), "hold": d(100), "auto": d(1000), "manuel": d(400), "autres": d(100)}
    # wallet supprimé depuis le snapshot : le reste des liquidités passe en « autres »
    p2 = postes(d(1500), d(0), d(0), d(0), {"1": {"liquid": d(1000)}}, {"1": "auto"})
    assert p2["autres"] == d(500)
    assert sum(p2.values(), Decimal(0)) == d(1500)
