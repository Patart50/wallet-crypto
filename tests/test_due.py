"""Fréquence des synchronisations et cumul Alchemy (wallet D-040)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from wallet_crypto import services
from wallet_crypto.config import Config
from wallet_crypto.db import Database, store
from wallet_crypto.db.models import SyncRun
from wallet_crypto.sync import RETRY_MS, is_due, record_usage

H = 3600_000
T0 = 1_800_000_000_000


def _db(tmp_path):
    db = Database(tmp_path / "w.db")
    db.init()
    return db


def _run(db, start, status):
    with db.session() as s:
        s.add(SyncRun(started_ms=start, finished_ms=start + 1000, status=status))


def test_due_after_interval(tmp_path):
    db, cfg = _db(tmp_path), Config(data_dir=tmp_path, sync_hours=6)
    assert is_due(db, cfg, T0)
    _run(db, T0, "ok")
    assert not is_due(db, cfg, T0 + 5 * H)
    assert is_due(db, cfg, T0 + 6 * H + 1000)


def test_failures_back_off(tmp_path):
    db, cfg = _db(tmp_path), Config(data_dir=tmp_path, sync_hours=6)
    _run(db, T0, "error")
    assert not is_due(db, cfg, T0 + 60_000)  # avant : nouvel essai chaque minute
    assert is_due(db, cfg, T0 + RETRY_MS)
    _run(db, T0 + RETRY_MS, "error")
    assert not is_due(db, cfg, T0 + 2 * RETRY_MS)
    assert is_due(db, cfg, T0 + 3 * RETRY_MS)  # 30 min après le 2e échec
    for i in range(10):
        _run(db, T0 + (4 + i) * H, "error")
    last = T0 + 13 * H
    assert not is_due(db, cfg, last + 5 * H)
    assert is_due(db, cfg, last + 6 * H)  # plafonné à l'intervalle
    _run(db, last + 6 * H, "ok")  # une réussite remet à zéro
    assert not is_due(db, cfg, last + 7 * H)


def test_usage_accumulates_and_rolls_over(tmp_path):
    db = _db(tmp_path)
    tz = ZoneInfo("Europe/Paris")
    calls = {"Alchemy · Portfolio assets/tokens/by-address": 3, "Hyperliquid · allMids": 9}
    d1 = int(datetime(2026, 10, 14, 10, tzinfo=tz).timestamp() * 1000)
    with db.session() as s:
        record_usage(s, calls, d1, tz)
        record_usage(s, calls, d1 + H, tz)
        record_usage(s, calls, d1 + 24 * H, tz)
        u = store.kv_get(s, "alchemy_usage")
    assert (u["month_total"], u["month_syncs"], u["day_total"]) == (9, 3, 3)
    with db.session() as s:
        record_usage(s, calls, int(datetime(2026, 11, 1, 0, 30, tzinfo=tz).timestamp() * 1000), tz)
        u = store.kv_get(s, "alchemy_usage")
    assert (u["month"], u["month_total"], u["month_syncs"]) == ("2026-11", 3, 1)


def test_usage_view_resets_on_new_month(tmp_path):
    db = _db(tmp_path)
    with db.session() as s:
        store.kv_set(s, "alchemy_usage", {"month": "2001-01", "month_total": 99, "day": "2001-01-01"})
    assert services.alchemy_usage(db, ZoneInfo("UTC"))["month_total"] == 0
