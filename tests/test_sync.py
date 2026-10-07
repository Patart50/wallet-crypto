import os
import time
from decimal import Decimal

import pytest

from conftest import ADDR_BTC, ADDR_EVM, ADDR_HL, FakeHttp, d, fixture
from test_sources import evm_routes, hl_routes, lock_hex
from wallet_crypto import cli
from wallet_crypto.config import Config, load_config, load_dotenv
from wallet_crypto.db import Database, store
from wallet_crypto.db.models import BalanceLine, HlFill, Snapshot, StakeEventRow, SyncRun, Wallet
from wallet_crypto.fmt import money, number, pct, qty
from wallet_crypto.lock import FileLock, LockBusy
from wallet_crypto.log import SecretFilter
from wallet_crypto.security import InputRejected
from wallet_crypto.sources.hyperliquid import API
from wallet_crypto.sync import run_sync

KEY = "KEY1234567890"


@pytest.fixture
def env(tmp_path):
    config = Config(data_dir=tmp_path / "data", alchemy_key=KEY)
    config.ensure_dirs()
    db = Database(config.db_path)
    db.init()
    return config, db


def full_http(wct_fail=False, hl_fail=False):
    http = FakeHttp()
    http.on_get("ticker/price", fixture("binance_ticker.json"))
    http.on_post(API, {"type": "spotMeta"}, fixture("hl_spot_meta.json"))
    http.on_post(API, {"type": "allMids"}, fixture("hl_all_mids.json"))
    if hl_fail:
        http.on_post(API, {"type": "clearinghouseState"}, RuntimeError("HL indisponible"))
    hl_routes(http)
    fills = fixture("hl_fills.json")
    http.on_post(
        API,
        {"type": "userFillsByTime"},
        lambda p: [f for f in fills if p["startTime"] <= f["time"] <= p["endTime"]],
    )
    http.on_post(API, {"type": "userFunding"}, fixture("hl_funding.json"))
    http.on_post(API, {"type": "delegatorHistory"}, fixture("hl_delegator_history.json"))
    http.on_post(API, {"type": "delegatorRewards"}, fixture("hl_delegator_rewards.json"))
    evm_routes(
        http,
        key=KEY,
        locks=lock_hex(100 * 10**18),
        claim="0x" + format(5 * 10**18, "064x"),
        wct_fail=wct_fail,
    )
    http.on_get("mempool.space", fixture("mempool_address.json"))
    return http


def add_wallets(db):
    with db.session() as s:
        store.add_wallet(s, "HL", ADDR_HL, "Compte 1", "Hyperliquid")
        store.add_wallet(s, "EVM", ADDR_EVM, "Ledger", "Froid")
        store.add_wallet(s, "BTC", ADDR_BTC, "Cold", "Bitcoin")


def test_full_sync(env):
    config, db = env
    add_wallets(db)
    rep = run_sync(db, config, full_http())
    assert rep.status == "ok" and rep.n_ok == 3 and rep.n_errors == 0
    assert rep.new_fills == 3 and rep.new_funding == 2 and rep.new_events == 7
    with db.session() as s:
        lines = {(r.wallet_id, r.coin): r for r in s.query(BalanceLine)}
        assert lines[(1, "USDC")].qty == d(1000)
        assert lines[(1, "HYPE")].px_sync == d(41)  # prix Binance noté à la sync
        assert lines[(2, "WCT_STAKED")].px_sync == d("0.3")
        assert lines[(3, "BTC")].qty == d("1.01") and lines[(3, "BTC")].px_sync == d(81000)
        assert isinstance(lines[(1, "USDC")].extra["official_value"], Decimal)
        snap = s.query(Snapshot).one()
        # HL : 1000 + 12,5×41 + 0,01×81000 + 20 + 250,5 + 115×41 ; EVM : 4500,75 + 500×0,9999 + 15 + 105×0,3 ; BTC
        hl = d(1000) + d("512.5") + d(810) + d(20) + d("250.5") + d(4715)
        evm = d("1.5") * d("3000.50") + d(500) * d("0.9999") + d(15) + d("31.5")
        assert snap.total == hl + evm + d("1.01") * d(81000)
        assert snap.detail["by_wallet_cat"]["1"]["stake"] == d("250.5") + d(4715)
        assert store.cached_price(s, "HYPE") == d(41)
        assert store.kv_get(s, "eur_per_usd") == 1 / d("1.08")
        assert "@107" in store.kv_get(s, "hl_spot_pairs")
        run = s.query(SyncRun).one()
        assert run.status == "ok" and run.n_ok == 3
        assert all(w.last_sync_ms and not w.last_error for w in s.query(Wallet))


def test_sync_is_idempotent_and_incremental(env):
    config, db = env
    add_wallets(db)
    run_sync(db, config, full_http())
    http = full_http()
    rep = run_sync(db, config, http)
    assert rep.new_fills == 0 and rep.new_funding == 0 and rep.new_events == 0
    fills_calls = [p for _, p in http.posts if p.get("type") == "userFillsByTime"]
    assert fills_calls[0]["startTime"] == 1767398400000  # reprend au dernier fill stocké
    with db.session() as s:
        assert s.query(HlFill).count() == 3 and s.query(StakeEventRow).count() == 7
        assert s.query(Snapshot).count() == 2


def test_failure_keeps_old_balances(env):
    config, db = env
    add_wallets(db)
    run_sync(db, config, full_http())
    rep = run_sync(db, config, full_http(hl_fail=True, wct_fail=True))
    assert rep.n_ok == 2 and rep.n_errors == 1
    assert "clearinghouseState" in rep.errors[0][1]
    assert any("WCT" in m for _, m in rep.warnings)
    with db.session() as s:
        hl = store.wallet_lines(s, 1)
        assert hl["USDC"].qty == d(1000)  # anciens soldes conservés
        assert s.get(Wallet, 1).last_error
        evm = store.wallet_lines(s, 2)
        assert evm["WCT_STAKED"].qty == d(100)  # repris de la sync précédente


def test_missing_alchemy_key_is_reported(env):
    config, db = env
    config.alchemy_key = ""
    add_wallets(db)
    rep = run_sync(db, config, full_http())
    assert rep.n_ok == 2 and rep.n_errors == 1
    assert "clé Alchemy manquante" in rep.errors[0][1]


def test_if_due_and_busy_and_empty(env):
    config, db = env
    assert run_sync(db, config, full_http()).status == "empty"
    add_wallets(db)
    assert run_sync(db, config, full_http(), if_due=True).status == "ok"
    assert run_sync(db, config, full_http(), if_due=True).status == "not_due"
    config.lock_path.write_text("123")
    assert run_sync(db, config, full_http()).status == "busy"
    old = time.time() - 3600
    os.utime(config.lock_path, (old, old))
    assert run_sync(db, config, full_http()).status == "ok"  # verrou périmé repris
    assert not config.lock_path.exists()


def test_lock():
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "x.lock"
    with FileLock(p), pytest.raises(LockBusy):
        FileLock(p).acquire()
    assert not p.exists()


def test_add_wallet_rules(env):
    _, db = env
    with db.session() as s:
        w = store.add_wallet(s, "hl", ADDR_HL.upper().replace("0X", "0x"), auto_trading=True)
        assert w.address == ADDR_HL and w.auto_trading
        e = store.add_wallet(s, "EVM", ADDR_HL, auto_trading=True)  # même adresse, autre réseau : permis
        assert not e.auto_trading  # case réservée à Hyperliquid
    with pytest.raises(InputRejected, match="déjà suivie"), db.session() as s:
        store.add_wallet(s, "HL", ADDR_HL)
    with pytest.raises(InputRejected, match="clé privée"), db.session() as s:
        store.add_wallet(s, "EVM", "0x" + "1" * 64)


def test_wallet_delete_cascades(env):
    config, db = env
    add_wallets(db)
    run_sync(db, config, full_http())
    with db.session() as s:
        s.delete(s.get(Wallet, 1))
    with db.session() as s:
        assert s.query(BalanceLine).filter_by(wallet_id=1).count() == 0


def test_manual_stake_in_snapshot(env):
    from wallet_crypto.db.models import ManualStakeRow, ManualStakeTxRow

    config, db = env
    add_wallets(db)
    with db.session() as s:
        s.add(ManualStakeRow(id=1, crypto="HYPE", start_ms=1, mode="rewards"))  # doublon du staking HL
        s.add(ManualStakeRow(id=2, crypto="BTC", start_ms=1, mode="rewards"))
        s.add(ManualStakeTxRow(position_id=1, time_ms=1, kind="STAKE", qty=d(10)))
        s.add(ManualStakeTxRow(position_id=2, time_ms=1, kind="STAKE", qty=d("0.1")))
    run_sync(db, config, full_http())
    with db.session() as s:
        snap = s.query(Snapshot).one()
        assert snap.manual == d(8100)
        assert snap.detail["duplicates"] == ["HYPE"]


# ---------------------------------------------------------------- CLI, configuration, format


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WALLET_CRYPTO_DATA", str(tmp_path / "d"))
    monkeypatch.setenv("ALCHEMY_API_KEY", KEY)
    assert cli.main(["wallet", "add", "HL,EVM", ADDR_EVM, "--label", "Principal", "--group", "MetaMask"]) == 0
    assert cli.main(["wallet", "add", "EVM", "0x" + "a" * 64]) == 1
    err = capsys.readouterr().err
    assert "clé privée" in err
    monkeypatch.setattr("wallet_crypto.sync.Http", lambda secrets: full_http())
    assert cli.main(["sync"]) == 0
    out = capsys.readouterr().out
    assert "2 wallet(s) lu(s)" in out and "Patrimoine" in out
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Patrimoine global" in out and "BTC LONG" in out
    assert cli.main(["status", "--eur"]) == 0
    assert " €" in capsys.readouterr().out
    assert cli.main(["trades"]) == 0
    assert "Trades clos : 1" in capsys.readouterr().out
    assert cli.main(["wallet", "list"]) == 0
    assert "MetaMask / Principal" in capsys.readouterr().out
    assert cli.main(["about"]) == 0
    out = capsys.readouterr().out
    assert "Arnaud (Patart50)" in out and KEY not in out and "KEY1…7890" in out
    log = (tmp_path / "d" / "logs" / "wallet-crypto.log").read_text(encoding="utf-8")
    assert KEY not in log
    assert cli.main(["wallet", "remove", "2"]) == 0


def test_dotenv_and_config(tmp_path):
    (tmp_path / ".env").write_text(
        '# commentaire\nALCHEMY_API_KEY="abc"\nexport WALLET_CRYPTO_SYNC_HOURS=2\nWALLET_CRYPTO_PASSWORD=secret-pass\nBAD\n'
    )
    assert load_dotenv(tmp_path / ".env")["WALLET_CRYPTO_SYNC_HOURS"] == "2"
    c = load_config(env={}, cwd=tmp_path)
    assert c.alchemy_key == "abc" and c.sync_hours == 2 and c.data_dir == tmp_path / "data"
    assert c.password == "secret-pass" and "secret-pass" in c.secrets
    c2 = load_config(env={"ALCHEMY_API_KEY": "env", "WALLET_CRYPTO_TZ": "Nowhere/X"}, cwd=tmp_path)
    assert c2.alchemy_key == "env" and str(c2.tz) == "UTC"


def test_secret_filter():
    import logging

    rec = logging.LogRecord("x", logging.INFO, "", 0, "url https://a/v2/%s/x", ("SECRETKEY123",), None)
    SecretFilter(["SECRETKEY123"]).filter(rec)
    assert "SECRETKEY123" not in rec.getMessage() and "SECR…Y123" in rec.getMessage()


def test_fmt():
    assert number(d("1234567.891")) == "1 234 567,89"
    assert money(d("-5")) == "-5,00 $"
    assert money(d(10), "EUR", rate=d("0.9")) == "9,00 €"
    assert money(d(10), "EUR") == "10,00 $"  # sans taux : reste en dollars
    assert pct(d("12.345")) == "+12,35 %"
    assert qty(d("0.123456789"), d(60000)) == "0,12345679"
    assert qty(d("1.5")) == "1,5"
    assert number(Decimal("Infinity")) == "∞"
