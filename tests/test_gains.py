from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from conftest import d
from wallet_crypto.core.gains import cum_series, day_grid, gains_timeline, hold_gain_series, inventory_at
from wallet_crypto.core.hold import HoldTx

DAY = 86_400_000
T0 = int(datetime(2026, 1, 1, 12, tzinfo=UTC).timestamp() * 1000)


def test_day_grid_ends_of_day_then_now():
    paris = ZoneInfo("Europe/Paris")
    g = day_grid(T0, T0 + 2 * DAY + 3600_000, paris)
    assert len(g) == 3 and g[-1] == T0 + 2 * DAY + 3600_000
    assert datetime.fromtimestamp(g[0] / 1000, paris).strftime("%d %H:%M") == "01 23:59"
    long_grid = day_grid(T0, T0 + 1000 * DAY, UTC, max_points=100)
    assert len(long_grid) <= 101 and long_grid[-1] == T0 + 1000 * DAY


def test_cum_series():
    grid = [10, 20, 30]
    assert cum_series([(5, d(1)), (15, d(2)), (20, d(3)), (40, d(9))], grid, 5) == [d(0), d(5), d(5)]


def test_inventory_and_hold_gain():
    txs = [HoldTx(T0, "BUY", d(1), d(100)), HoldTx(T0 + DAY, "SELL", d("0.5"), d(150))]
    assert inventory_at(txs, T0 + DAY) == (d("0.5"), d(50), d(25))
    prices = {T0: d(100), T0 + DAY: d(150), T0 + 2 * DAY: d(200)}

    def pf(base, t):
        return max((p for tt, p in prices.items() if tt <= t), default=None) if base == "BTC" else None

    grid = [T0 + DAY, T0 + 2 * DAY]
    vals, excluded = hold_gain_series({"BTC": txs, "XYZ": [HoldTx(T0, "BUY", d(1), d(1))]}, grid, T0, pf)
    # départ : valeur 0 de gain ; jour 1 : 25 réalisé + 0,5 × 150 − 50 = 50 ; jour 2 : 25 + 100 − 50 = 75
    assert vals == [d(50), d(75)]
    assert excluded == ["XYZ"]


def test_gains_timeline():
    fills = [
        {
            "address": "0xauto",
            "coin": "BTC",
            "time_ms": T0 + 100,
            "closed_pnl": d(10),
            "fee": d(1),
            "fee_token": "USDC",
        },
        {
            "address": "0xman",
            "coin": "ETH",
            "time_ms": T0 + 200,
            "closed_pnl": d(-5),
            "fee": d("0.5"),
            "fee_token": "USDC",
        },
        {"address": "0xman", "coin": "@107", "time_ms": T0 + 300, "closed_pnl": d(99), "fee": d(0)},
    ]
    fundings = [{"address": "0xauto", "time_ms": T0 + 400, "usdc": d(-2)}]
    res = gains_timeline(
        start_ms=T0,
        now_ms=T0 + DAY,
        fills=fills,
        fundings=fundings,
        account_kinds={"0xauto": "auto", "0xman": "manuel"},
        stake_rewards=[("HYPE", T0 + 500, d(1)), ("NOPX", T0 + 600, d(5))],
        pending=[("WCT", d(10))],
        hold_txs={},
        price_fn=lambda b, t: {"HYPE": d(40), "WCT": d("0.5")}.get(b),
    )
    s = res["series"]
    assert s["auto"][-1] == d(7) and s["manuel"][-1] == d("-5.5")
    assert s["stake"][-1] == d(45) and res["unpriced_rewards"] == 1
    assert s["total"][-1] == d(7) + d("-5.5") + d(45)
