"""Couche entre la base et l'interface (J2) : services de vue, prix historiques, réglages,
sauvegarde, mot de passe. Base de démonstration fictive, aucun appel réseau."""

from decimal import Decimal

import pytest

from conftest import ADDR_HL, FakeHttp, d
from wallet_crypto import auth, backup, history, services
from wallet_crypto.config import Config
from wallet_crypto.db import Database, store
from wallet_crypto.db.models import HoldTxRow, KlineCache, StakeEventRow
from wallet_crypto.demo import build_demo
from wallet_crypto.settings import effective_config, load_settings, save_setting
from wallet_crypto.sources.hyperliquid import API

DAY = 86_400_000
NOW = 1_790_000_000_000  # date fixe : résultats reproductibles


@pytest.fixture
def demo(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.ensure_dirs()
    db = Database(config.db_path)
    build_demo(db, now=NOW)
    return config, db


# ---------------------------------------------------------------- démo et vues
def test_demo_is_consistent(demo):
    config, db = demo
    dv = services.dashboard(db, config, now=NOW)
    assert dv.has_wallets and dv.n_wallets == 5
    assert dv.total == dv.liquid + dv.hold + dv.stake + dv.manual
    assert sum(dv.postes.values(), Decimal(0)) == dv.total
    assert not dv.unpriced and not dv.duplicates
    assert {d_.label for d_ in dv.deltas} == {"depuis le début", "7 jours", "24 h"}
    points = services.patrimoine_series(db, dv, NOW)
    last_snap, live = points[-2][1], points[-1][1]
    assert abs(sum(live.values(), Decimal(0)) - sum(last_snap.values(), Decimal(0))) < dv.total * Decimal(
        "0.05"
    )


def test_hold_view_demo_has_no_spurious_alert(demo):
    _, db = demo
    hv = services.hold_view(db, include_staked=True)
    by = {c.base: c.position for c in hv.cards}
    assert by["HYPE"].excess == 0 and by["HYPE"].unknown == 0
    assert by["JUP"].unknown == d(820)  # alerte volontaire de la démo : aucun achat saisi
    assert by["ETH"].pmp > 0 and hv.total_value > 0


def test_staking_trades_wallets_views(demo):
    config, db = demo
    sv = services.staking_view(db, config, now=NOW)
    assets = {a.asset: a for a in sv.autos}
    assert assets["HYPE"].metrics.capital == d(400) and assets["HYPE"].metrics.apr_avg > 0
    assert assets["WCT"].pending == d("118.4")
    assert sv.vaults == d("1534.2")
    assert len(sv.manuals) == 1 and not sv.manuals[0].duplicate
    tv = services.trades_view(db, now=NOW)
    assert len(tv.selected) == 2  # tous les comptes Hyperliquid par défaut
    assert tv.stats["n"] > 50
    tv_bot = services.trades_view(
        db, selected=["0x2222222222222222222222222222222222222222"], period_days=30, now=NOW
    )
    assert 0 < tv_bot.n_trades < tv.n_trades
    groups = services.wallets_view(db)
    assert set(groups) == {"Hyperliquid", "MetaMask", "Phantom", "Bitcoin"}
    mt = services.manual_trades_view(db)
    assert mt[0].metrics["qty"] == d(6)


def test_gains_use_cached_history(demo):
    config, db = demo
    opts = services.gain_start_options(db, config, NOW)
    key = services.default_gain_start(opts)
    hp = history.HistoricalPrices(db, NOW)
    res = services.gains_data(db, config, opts[key][1], hp, NOW)
    s = res["series"]
    assert len(s["total"]) == len(res["grid"]) and res["grid"][-1] == NOW
    assert s["stake"][-1] > 0 and s["auto"][-1] != 0
    assert s["total"][-1] == s["stake"][-1] + s["hold"][-1] + s["auto"][-1] + s["manuel"][-1]
    assert not res["excluded"] and not hp.missing


def test_manual_entries_validation(demo):
    _, db = demo
    with pytest.raises(ValueError):
        services.add_hold_tx(db, "ETH", "BUY", NOW, d(-1), d(10))
    with pytest.raises(ValueError):
        services.add_hold_tx(db, "", "BUY", NOW, d(1), d(10))
    services.add_hold_tx(db, "eth", "FEE", NOW, d("0.001"), d(99))
    with db.session() as s:
        fee = s.query(HoldTxRow).order_by(HoldTxRow.id.desc()).first()
        assert fee.crypto == "ETH" and fee.price == 0
    tid = services.create_manual_trade(db, "BTC", "SHORT", d(2), NOW, d("0.1"), d(80000))
    with pytest.raises(ValueError, match="supérieure"):
        services.add_manual_trade_tx(db, tid, "REDUCE", NOW + 1, d(1), d(79000))
    pid = services.create_manual_stake(db, "ATOM", NOW - 10 * DAY, "apr", 1, d(10), d(15))
    services.add_manual_stake_rate(db, pid, NOW - 5 * DAY, d(10))
    added, errors = services.add_wallets(
        db, ["HL", "EVM"], [ADDR_HL, "0x" + "ab" * 32], "G", "L", True, False
    )
    assert errors and all("clé privée" in e or "déjà suivie" in e for e in errors)


# ---------------------------------------------------------------- prix historiques
def test_history_update_cache_and_lookup(tmp_path):
    db = Database(tmp_path / "h.db")
    db.init()
    t0 = 1_767_225_600_000  # 01/01/2026 00:00 UTC
    with db.session() as s:
        s.add(HoldTxRow(crypto="BTC", side="BUY", time_ms=t0 + 5 * DAY, qty=d(1), price=d(1)))
        s.add(
            StakeEventRow(
                source="HL_HYPE",
                address="x",
                asset="HYPE",
                time_ms=t0 + 2 * DAY,
                kind="REWARD",
                qty=d(1),
                ext_id="e1",
            )
        )
        s.add(HoldTxRow(crypto="NOPE", side="BUY", time_ms=t0, qty=d(1), price=d(1)))
        s.add(HoldTxRow(crypto="USDC", side="BUY", time_ms=t0, qty=d(1), price=d(1)))
    http = FakeHttp()
    http.on_get(
        "/klines",
        lambda p: [
            [t0 + i * DAY, "0", "0", "0", str(100 + i), "0"]
            for i in range(10)
            if p["startTime"] <= t0 + i * DAY <= p["endTime"]
        ],
    )
    http.on_post(
        API,
        {"type": "candleSnapshot"},
        lambda p: [
            {"t": t0 + i * DAY, "c": str(40 + i)}
            for i in range(10)
            if p["req"]["startTime"] <= t0 + i * DAY <= p["req"]["endTime"]
        ],
    )
    now = t0 + 9 * DAY + 3600_000
    with db.session() as s:
        syms = history.update_cache(s, http, {"BTCUSDT": d(1)}, {"HYPE": d(1)}, {}, now)
    assert syms == {"BTC": "BINANCE:BTCUSDT", "HYPE": "HL:HYPE"}
    with db.session() as s:
        assert s.query(KlineCache).filter_by(symbol="BINANCE:BTCUSDT").count() == 6  # du 4e au 9e jour
    hp = history.HistoricalPrices(db, now, current_fn=lambda b: d(999) if b == "BTC" else None)
    assert hp("BTC", t0 + 5 * DAY + 3600_000) == d(105)
    assert hp("BTC", now) == d(999)  # instant récent : prix courant
    assert hp("HYPE", t0 + 2 * DAY) == d(42)
    assert hp("BTC", t0) is None  # avant le cache
    assert hp("USDT", t0) == 1
    assert hp("NOPE", t0) is None and "NOPE" in hp.missing
    # deuxième passage : seulement la suite (et la bougie du jour)
    with db.session() as s:
        history.update_cache(s, http, {"BTCUSDT": d(1)}, {"HYPE": d(1)}, {}, now)
    starts = [p["startTime"] for _, p in http.gets if p]
    assert starts[-1] == t0 + 9 * DAY


def test_history_gap_limit(tmp_path):
    db = Database(tmp_path / "g.db")
    db.init()
    with db.session() as s:
        store.kv_set(s, "kline_symbols", {"X": "BINANCE:XUSDT"})
        s.add(KlineCache(symbol="BINANCE:XUSDT", day_ms=0, close=d(1)))
    hp = history.HistoricalPrices(db, 100 * DAY)
    assert hp("X", 2 * DAY) == d(1)
    assert hp("X", 5 * DAY) is None  # plus de trois jours sans cours : pas de prix périmé


# ---------------------------------------------------------------- réglages, sauvegarde, mot de passe
def test_settings_priority(tmp_path):
    db = Database(tmp_path / "s.db")
    db.init()
    base = Config(data_dir=tmp_path)
    save_setting(db, "alchemy_key", "  saved-key-1234567890  ")
    save_setting(db, "sync_hours", 100)
    save_setting(db, "currency", "EUR")
    st = load_settings(db, base)
    assert st.alchemy_key == "saved-key-1234567890" and not st.alchemy_from_env
    assert st.sync_hours == 48 and st.currency == "EUR" and st.theme == "dark"
    env = Config(data_dir=tmp_path, alchemy_key="env-key-1234567890")
    assert load_settings(db, env).alchemy_from_env
    assert effective_config(db, env).alchemy_key == "env-key-1234567890"
    assert effective_config(db, base).alchemy_key == "saved-key-1234567890"
    with pytest.raises(ValueError):
        save_setting(db, "currency", "BTC")
    with pytest.raises(ValueError):
        save_setting(db, "inconnu", 1)


def test_backup_roundtrip(demo, tmp_path):
    config, db = demo
    data = backup.export_bytes(db)
    assert data[:16] == b"SQLite format 3\x00"
    other = Database(tmp_path / "other" / "w.db")
    other.init()
    keep = backup.import_bytes(other, data)
    assert keep.exists()
    with other.session() as s:
        assert len(store.list_wallets(s)) == 5
    with pytest.raises(backup.BackupError):
        backup.import_bytes(other, b"pas une base")


def test_password_hash():
    h = auth.hash_password("correct horse")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("wrong", h)
    assert not auth.verify_password("x", None)
    with pytest.raises(ValueError):
        auth.hash_password("court")
    assert auth.is_loopback("127.0.0.1") and auth.is_loopback("::1") and auth.is_loopback("localhost")
    assert not auth.is_loopback("0.0.0.0") and not auth.is_loopback("192.168.1.5")


def test_storage_secret_is_stable(tmp_path):
    a = auth.storage_secret(tmp_path)
    assert a == auth.storage_secret(tmp_path) and len(a) > 30
    assert oct((tmp_path / "secret.key").stat().st_mode)[-3:] == "600"


# ---------------------------------------------------------------- nettoyage de l'historique (D-031)
def test_delete_wallet_purges_its_history(demo):
    from wallet_crypto.db.models import HlFill, Snapshot, Wallet

    config, db = demo
    with db.session() as s:
        evm = s.query(Wallet).filter_by(network="EVM").one()
        evm_id, hl_count = str(evm.id), s.query(HlFill).count()
        before = {sn.id: (sn.total, sn.detail["by_wallet_cat"][evm_id]) for sn in s.query(Snapshot)}
    n = services.delete_wallet(db, int(evm_id))
    assert n["snapshots"] == len(before) and n["stake_events"] > 0 and n["fills"] == 0
    with db.session() as s:
        assert s.query(HlFill).count() == hl_count  # l'historique Hyperliquid n'est pas touché
        assert s.query(StakeEventRow).filter_by(source="WCT_OP").count() == 0
        assert s.query(StakeEventRow).filter_by(source="HL_HYPE").count() > 0
        for sn in s.query(Snapshot):
            total0, cats = before[sn.id]
            assert sn.total == total0 - sum(cats.values(), Decimal(0))
            assert evm_id not in sn.detail["by_wallet_cat"] and "by_coin" not in sn.detail
            assert (
                sn.total
                == sum((sum(c.values(), Decimal(0)) for c in sn.detail["by_wallet_cat"].values()), Decimal(0))
                + sn.manual
            )
    assert services.purge_history(db) == {"snapshots": 0, "fills": 0, "funding": 0, "stake_events": 0}
    dv = services.dashboard(db, config, now=NOW)
    points = services.patrimoine_series(db, dv, NOW)
    assert all(sum(p.values(), Decimal(0)) < d(100000) for _, p in points)


def test_purge_keeps_same_address_on_other_network(tmp_path):
    from wallet_crypto.db.models import HlFill

    db = Database(tmp_path / "p.db")
    db.init()
    addr = "0x4444444444444444444444444444444444444444"
    with db.session() as s:
        hl = store.add_wallet(s, "HL", addr)
        evm = store.add_wallet(s, "EVM", addr)
        hl_id, evm_id = hl.id, evm.id
        store.store_fills(s, [{"address": addr, "tid": 1, "coin": "BTC", "side": "B", "px": d(1), "sz": d(1),
                               "start_position": d(0), "closed_pnl": d(0), "fee": d(0), "builder_fee": d(0),
                               "time_ms": 1, "is_spot": False}])  # fmt: skip
        store.store_stake_events(s, [
            {"source": "WCT_OP", "address": addr, "asset": "WCT", "time_ms": 1, "kind": "DEPOSIT", "qty": d(3497651), "ext_id": "w1"},
            {"source": "HL_HYPE", "address": addr, "asset": "HYPE", "time_ms": 1, "kind": "DEPOSIT", "qty": d(10), "ext_id": "h1"},
        ])  # fmt: skip
    services.delete_wallet(db, evm_id)
    with db.session() as s:
        assert s.query(HlFill).count() == 1
        assert [e.source for e in s.query(StakeEventRow)] == ["HL_HYPE"]
    services.delete_wallet(db, hl_id)
    with db.session() as s:
        assert s.query(HlFill).count() == 0 and s.query(StakeEventRow).count() == 0


def test_open_positions_moved_to_trades(demo):
    _, db = demo
    pos = services.open_positions(db)
    assert {p["coin"] for p in pos} == {"ETH", "BTC"} and any(p["auto"] for p in pos)
    assert services.open_positions(db, ["0x1111111111111111111111111111111111111111"])[0]["coin"] == "ETH"
