"""Données de démonstration : un patrimoine entièrement **fictif** pour essayer l'interface sans
adresse ni clé (``wallet-crypto demo`` puis ``wallet-crypto serve --demo``).

Adresses inventées, montants générés (graine fixe : même résultat à chaque fois), historique de
90 jours, prix historiques fictifs en cache : la démo ne contacte aucune API.
"""

from __future__ import annotations

import random
from decimal import Decimal

from .core.assets import AssetLine
from .db import Database, store
from .db.models import (
    HlPosition,
    HoldTxRow,
    KlineCache,
    ManualStakeRateRow,
    ManualStakeRow,
    ManualStakeTxRow,
    ManualTradeRow,
    ManualTradeTxRow,
    Snapshot,
    SyncRun,
)
from .money import D

DAY = 86_400_000
H = 3_600_000

DEMO_ADDR = {
    "hl": "0x1111111111111111111111111111111111111111",
    "bot": "0x2222222222222222222222222222222222222222",
    "evm": "0x3333333333333333333333333333333333333333",
    "btc": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",  # adresse d'exemple de la BIP-173
}
PRICES = {
    "BTC": "81250",
    "ETH": "3020",
    "HYPE": "41.2",
    "SOL": "152.4",
    "WCT": "0.31",
    "ARB": "0.62",
    "JUP": "0.85",
    "DOT": "6.4",
}


def q(x, places=8) -> Decimal:
    return D(x).quantize(Decimal(1).scaleb(-places))


def _walk(rng: random.Random, end: float, days: int, vol: float, drift: float = 0.0015) -> list[float]:
    """Marche aléatoire qui finit exactement à ``end``."""
    vals = [1.0]
    for _ in range(days):
        vals.append(vals[-1] * (1 + rng.gauss(drift, vol)))
    k = end / vals[-1]
    return [v * k for v in vals]


def build_demo(db: Database, now: int | None = None) -> None:
    now = now or store.now_ms()
    rng = random.Random(42)
    db.init()
    with db.session() as s:
        if store.list_wallets(s):
            raise RuntimeError("Le dossier de démonstration contient déjà des données.")
        hl = store.add_wallet(s, "HL", DEMO_ADDR["hl"], "Principal", "Hyperliquid")
        bot = store.add_wallet(s, "HL", DEMO_ADDR["bot"], "Bot", "Hyperliquid", auto_trading=True)
        evm = store.add_wallet(s, "EVM", DEMO_ADDR["evm"], "Compte 1", "MetaMask")
        sol = store.add_wallet(s, "SOL", "So1aNaTestAddre55111111111111111111111111", "Principal", "Phantom")
        btc = store.add_wallet(s, "BTC", DEMO_ADDR["btc"], "Cold", "Bitcoin")
        ids = {"hl": hl.id, "bot": bot.id, "evm": evm.id, "sol": sol.id, "btc": btc.id}
        for w in (hl, bot, evm, sol, btc):
            w.last_sync_ms = now - 40 * 60_000
        for base, p in PRICES.items():
            store.set_cached_price(s, base, D(p), "démo")
        store.kv_set(s, "eur_per_usd", D("0.9234"))
        store.kv_set(
            s,
            "hl_spot_pairs",
            {
                "@107": {"base": "HYPE", "raw": "HYPE", "quote": "USDC"},
                "@142": {"base": "BTC", "raw": "UBTC", "quote": "USDC"},
            },
        )
        store.kv_set(s, "demo", True)
        store.kv_set(  # volumes fictifs, pour montrer l'affichage (D-036)
            s,
            "last_sync_calls",
            {
                "ts_ms": now - 40 * 60_000,
                "calls": {
                    "Alchemy · Portfolio assets/tokens/by-address": 2,
                    "Alchemy · opt-mainnet · eth_call": 3,
                    "Binance · ticker": 1,
                    "Hyperliquid · clearinghouseState": 2,
                    "Hyperliquid · userFillsByTime": 2,
                },
            },
        )

        def px(b):
            return D(PRICES[b])

        lines = {
            "hl": {
                "USDC": AssetLine(
                    "USDC",
                    D("4210.55"),
                    D("4210.55"),
                    "hl_unified",
                    extra={
                        "mode": "unified",
                        "hold": D("890"),
                        "transferable": D("3320.55"),
                        "margin_used": D("890"),
                        "upnl": D("164.2"),
                        "n_pos": 1,
                        "official_value": D("12925.4"),
                        "account_mode": "unifiedaccount",
                    },
                ),
                "HYPE": AssetLine("HYPE", D("89.804"), None, "hl_spot", px("HYPE")),
                "BTC": AssetLine("BTC", D("0.0412"), None, "hl_spot", px("BTC")),
                "HYPE_STAKED": AssetLine(
                    "HYPE_STAKED",
                    D("402.7097"),
                    None,
                    "hl_deleg",
                    px("HYPE"),
                    {"delegated": D("402.7097"), "undelegated": D(0), "pending_withdrawal": D(0)},
                ),
                "HLP_VAULTS": AssetLine("HLP_VAULTS", D("1534.2"), D("1534.2"), "hl_vault"),
            },
            "bot": {
                "USDC": AssetLine(
                    "USDC",
                    D("6120.8"),
                    D("6120.8"),
                    "hl_unified",
                    extra={
                        "mode": "unified",
                        "hold": D("410"),
                        "transferable": D("5710.8"),
                        "margin_used": D("410"),
                        "upnl": D("-38.4"),
                        "n_pos": 1,
                        "official_value": D("6120.8"),
                        "account_mode": "unifiedaccount",
                    },
                ),
            },
            "evm": {
                "ETH": AssetLine(
                    "ETH",
                    D("2.41"),
                    D("2.41") * px("ETH"),
                    "alchemy",
                    extra={"chains": {"eth-mainnet": D("1.9"), "arb-mainnet": D("0.51")}},
                ),
                "USDC": AssetLine(
                    "USDC", D("1830"), D("1829.6"), "alchemy", extra={"chains": {"arb-mainnet": D("1830")}}
                ),
                "WCT": AssetLine("WCT", D("912"), D("912") * px("WCT"), "alchemy"),
                "ARB": AssetLine("ARB", D("1540"), D("1540") * px("ARB"), "alchemy"),
                "WCT_STAKED": AssetLine(
                    "WCT_STAKED",
                    D("5040"),
                    None,
                    "wct_lock",
                    px("WCT"),
                    {"lock_end": int((now + 300 * DAY) / 1000), "permanent": False},
                ),
                "WCT_PENDING": AssetLine("WCT_PENDING", D("118.4"), None, "wct_claimable", px("WCT")),
            },
            "sol": {
                "SOL": AssetLine("SOL", D("34.2"), D("34.2") * px("SOL"), "alchemy"),
                "JUP": AssetLine("JUP", D("820"), D("820") * px("JUP"), "alchemy"),
            },
            "btc": {"BTC": AssetLine("BTC", D("0.35"), None, "mempool", px("BTC"))},
        }
        for k, ls in lines.items():
            store.replace_lines(s, ids[k], ls, ts=now - 40 * 60_000)
        s.add(
            HlPosition(
                wallet_id=hl.id,
                coin="ETH",
                side="LONG",
                size=D("1.5"),
                entry=D("2910.5"),
                value=D("4530"),
                upnl=D("164.2"),
                lev=D(5),
                liq_px=D("2390"),
                roe=D("18.8"),
            )
        )
        s.add(
            HlPosition(
                wallet_id=bot.id,
                coin="BTC",
                side="SHORT",
                size=D("0.05"),
                entry=D("80480"),
                value=D("4062.5"),
                upnl=D("-38.4"),
                lev=D(10),
                liq_px=D("88100"),
                roe=D("-9.5"),
            )
        )

        # ---- prix historiques fictifs (cache) sur 120 jours
        days = 120
        today = now - now % DAY
        series = {}
        symbols = {}
        for base, vol in (
            ("BTC", 0.025),
            ("ETH", 0.032),
            ("HYPE", 0.05),
            ("SOL", 0.04),
            ("WCT", 0.06),
            ("DOT", 0.035),
            ("ARB", 0.045),
            ("JUP", 0.05),
        ):
            vals = _walk(rng, float(PRICES[base]), days, vol)
            series[base] = vals
            symbols[base] = f"BINANCE:{base}USDT"
            for i, v in enumerate(vals):
                s.add(
                    KlineCache(symbol=f"BINANCE:{base}USDT", day_ms=today - (days - i) * DAY, close=q(v, 6))
                )

        store.kv_set(s, "kline_symbols", symbols)

        def hist(base, t):
            i = max(0, min(days, days - (today - (t - t % DAY)) // DAY))
            return D(series[base][int(i)])

        # ---- fills perp : trades aller-retour
        tid = 1000
        fills = []
        for addr, n, edge in ((DEMO_ADDR["hl"], 45, 0.004), (DEMO_ADDR["bot"], 120, 0.0015)):
            t = now - 88 * DAY
            for _ in range(n):
                coin = rng.choice(["BTC", "ETH", "SOL", "HYPE"])
                side = rng.choice([1, -1])
                p_in = float(hist(coin, t))
                notional = rng.uniform(800, 4000)
                sz = q(notional / p_in, 4)
                hold = int(rng.uniform(0.5, 30) * H)
                move = rng.gauss(edge, 0.02)
                p_out = p_in * (1 + side * move)
                pnl = q(float(sz) * (p_out - p_in) * side, 4)
                fee_in = q(notional * 0.00045, 4)
                fee_out = q(float(sz) * p_out * 0.00045, 4)
                tid += 1
                fills.append(
                    {
                        "address": addr,
                        "tid": tid,
                        "oid": tid,
                        "coin": coin,
                        "side": "B" if side > 0 else "A",
                        "px": q(p_in, 4),
                        "sz": sz,
                        "dir": "Open Long" if side > 0 else "Open Short",
                        "start_position": D(0),
                        "closed_pnl": D(0),
                        "fee": fee_in,
                        "fee_token": "USDC",
                        "builder_fee": D(0),
                        "time_ms": t,
                        "hash": None,
                        "crossed": True,
                        "liquidation": False,
                        "is_spot": False,
                    }
                )
                tid += 1
                fills.append(
                    {
                        "address": addr,
                        "tid": tid,
                        "oid": tid,
                        "coin": coin,
                        "side": "A" if side > 0 else "B",
                        "px": q(p_out, 4),
                        "sz": sz,
                        "dir": "Close Long" if side > 0 else "Close Short",
                        "start_position": sz if side > 0 else -sz,
                        "closed_pnl": pnl,
                        "fee": fee_out,
                        "fee_token": "USDC",
                        "builder_fee": D(0),
                        "time_ms": t + hold,
                        "hash": None,
                        "crossed": True,
                        "liquidation": False,
                        "is_spot": False,
                    }
                )
                t += hold + int(rng.uniform(2, 30) * H)
                if t > now - 2 * H:
                    break
        # fills spot : achats de HYPE et de BTC sur Hyperliquid
        for i, (pair, base, qty) in enumerate(
            (
                ("@107", "HYPE", "180"),
                ("@107", "HYPE", "160"),
                ("@107", "HYPE", "150"),
                ("@142", "BTC", "0.0412"),
            )
        ):
            t = now - (75 - i * 15) * DAY
            p = hist(base, t)
            tid += 1
            fills.append(
                {
                    "address": DEMO_ADDR["hl"],
                    "tid": tid,
                    "oid": tid,
                    "coin": pair,
                    "side": "B",
                    "px": q(p, 4),
                    "sz": D(qty),
                    "dir": "Buy",
                    "start_position": D(0),
                    "closed_pnl": D(0),
                    "fee": q(D(qty) * D("0.0004"), 6),
                    "fee_token": "HYPE" if base == "HYPE" else "UBTC",
                    "builder_fee": D(0),
                    "time_ms": t,
                    "hash": None,
                    "crossed": True,
                    "liquidation": False,
                    "is_spot": True,
                }
            )
        store.store_fills(s, fills)
        funding = []
        for k in range(0, 88 * 24, 8):
            t = now - 88 * DAY + k * H
            funding.append(
                {
                    "address": DEMO_ADDR["bot"],
                    "time_ms": t,
                    "coin": "BTC",
                    "usdc": q(rng.gauss(-0.35, 0.4), 4),
                    "szi": D("-0.05"),
                    "rate": D("0.0000125"),
                    "hash": None,
                }
            )
        store.store_funding(s, funding)

        # ---- staking automatique : HYPE (récompenses quotidiennes recomposées) et WCT (hebdomadaires)
        ev = [
            {
                "source": "HL_HYPE",
                "address": DEMO_ADDR["hl"],
                "asset": "HYPE",
                "time_ms": now - 80 * DAY,
                "kind": "DEPOSIT",
                "qty": D(400),
                "hash": "0xdemo01",
                "ext_id": "demo:hl:dep",
                "detail": None,
            }
        ]
        for d in range(1, 80):
            ev.append(
                {
                    "source": "HL_HYPE",
                    "address": DEMO_ADDR["hl"],
                    "asset": "HYPE",
                    "time_ms": now - (80 - d) * DAY,
                    "kind": "REWARD",
                    "qty": D("0.0343"),
                    "hash": None,
                    "ext_id": f"demo:hl:r{d}",
                    "detail": "delegation",
                }
            )
        ev.append(
            {
                "source": "WCT_OP",
                "address": DEMO_ADDR["evm"],
                "asset": "WCT",
                "time_ms": now - 70 * DAY,
                "kind": "DEPOSIT",
                "qty": D(4800),
                "hash": "0xdemo02",
                "ext_id": "demo:wct:dep",
                "detail": None,
            }
        )
        for w in range(1, 10):
            t = now - (70 - 7 * w) * DAY
            ev.append(
                {
                    "source": "WCT_OP",
                    "address": DEMO_ADDR["evm"],
                    "asset": "WCT",
                    "time_ms": t,
                    "kind": "REWARD",
                    "qty": D("26.7"),
                    "hash": f"0xdemor{w}",
                    "ext_id": f"demo:wct:r{w}",
                    "detail": None,
                }
            )
            if w in (3, 6, 9):
                ev.append(
                    {
                        "source": "WCT_OP",
                        "address": DEMO_ADDR["evm"],
                        "asset": "WCT",
                        "time_ms": t + H,
                        "kind": "DEPOSIT",
                        "qty": D("80"),
                        "hash": f"0xdemol{w}",
                        "ext_id": f"demo:wct:l{w}",
                        "detail": None,
                    }
                )
        store.store_stake_events(s, ev)

        # ---- saisies : achats hors Hyperliquid, staking et trade sur d'autres plateformes
        for crypto, days_ago, qty in (
            ("ETH", 85, "1.6"),
            ("ETH", 40, "0.812"),
            ("SOL", 60, "34.2"),
            ("BTC", 88, "0.35"),
            ("ARB", 50, "1540"),
            ("WCT", 72, "5900"),
        ):
            t = now - days_ago * DAY
            s.add(
                HoldTxRow(
                    crypto=crypto,
                    side="BUY",
                    time_ms=t,
                    qty=D(qty),
                    price=q(hist(crypto, t), 4),
                    notes="démo",
                )
            )
        s.add(
            HoldTxRow(
                crypto="ETH",
                side="FEE",
                time_ms=now - 39 * DAY,
                qty=D("0.002"),
                price=D(0),
                notes="frais de pont (démo)",
            )
        )
        pos = ManualStakeRow(
            crypto="DOT",
            start_ms=now - 65 * DAY,
            mode="apr",
            compound_days=1,
            platform_url="https://example.org",
            notes="Plateforme fictive (démo)",
        )
        s.add(pos)
        s.flush()
        s.add(ManualStakeRateRow(position_id=pos.id, start_ms=now - 65 * DAY, end_ms=None, apr_pct=D(12)))
        s.add(ManualStakeTxRow(position_id=pos.id, time_ms=now - 65 * DAY, kind="STAKE", qty=D(500)))
        tr = ManualTradeRow(
            crypto="SOL",
            direction="LONG",
            leverage=D(3),
            open_ms=now - 20 * DAY,
            platform="Plateforme X (démo)",
        )
        s.add(tr)
        s.flush()
        p0 = q(hist("SOL", now - 20 * DAY), 2)
        s.add(ManualTradeTxRow(trade_id=tr.id, time_ms=now - 20 * DAY, kind="OPEN", qty=D(10), price=p0))
        s.add(
            ManualTradeTxRow(
                trade_id=tr.id,
                time_ms=now - 8 * DAY,
                kind="REDUCE",
                qty=D(4),
                price=q(hist("SOL", now - 8 * DAY), 2),
            )
        )

        # ---- relevés du patrimoine : un toutes les 6 h sur 90 jours
        summary_now = None
        from .core.portfolio import portfolio_summary

        wa = store.load_wallet_assets(s)
        from .core.portfolio import auto_stake_bases

        s.flush()
        manual_items = store.manual_stake_items(
            s, lambda b: store.cached_price(s, b), auto_stake_bases(wa), now
        )
        summary_now = portfolio_summary(wa, None, lambda b: store.cached_price(s, b), manual_items)
        total_now = float(summary_now.total)
        n = 90 * 4
        path = _walk(rng, total_now, n, 0.006, 0.0003)
        start_scale = 0.9  # apports progressifs (dépôts)
        for i in range(n):
            t = now - (n - i) * 6 * H
            k = path[i] / total_now * (start_scale + (1 - start_scale) * i / n)
            cat = {
                wid: {c: q(v * Decimal(str(k)), 2) for c, v in cats.items()}
                for wid, cats in summary_now.by_wallet_cat.items()
            }
            liquid = sum((c["liquid"] for c in cat.values()), Decimal(0))
            hold = sum((c["hold"] for c in cat.values()), Decimal(0))
            stake = sum((c["stake"] for c in cat.values()), Decimal(0))
            manual = q(summary_now.manual * Decimal(str(k)), 2)
            s.add(
                Snapshot(
                    ts_ms=t,
                    total=liquid + hold + stake + manual,
                    liquid=liquid,
                    hold=hold,
                    stake=stake,
                    manual=manual,
                    n_wallets=5,
                    n_errors=0,
                    n_unpriced=0,
                    detail={"by_wallet_cat": {str(w): c for w, c in cat.items()}},
                )
            )
        s.add(
            SyncRun(
                started_ms=now - 40 * 60_000, finished_ms=now - 39 * 60_000, status="ok", n_ok=5, n_errors=0
            )
        )
