"""Migrations Alembic (wallet D-018, D-034)."""

from __future__ import annotations

import sqlite3
import stat
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from wallet_crypto import backup
from wallet_crypto.db import Database, migrate
from wallet_crypto.db.models import KV, Base, HoldTxRow, Wallet


def _diffs(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)


def test_new_base_matches_models(tmp_path):
    db = Database(tmp_path / "w.db")
    assert db.init() is None
    with db.engine.connect() as conn:
        assert migrate.current(conn) == migrate.head()
    assert _diffs(tmp_path / "w.db") == []


def test_legacy_base_is_stamped_and_kept(tmp_path):
    path = tmp_path / "w.db"
    engine = create_engine(f"sqlite:///{path}")
    legacy = [t for t in Base.metadata.sorted_tables if t.name != "kline_cache"]  # base J1
    Base.metadata.create_all(engine, tables=legacy)
    with engine.begin() as conn:
        conn.execute(KV.__table__.insert().values(key="schema_version", value=1))
        conn.execute(
            HoldTxRow.__table__.insert().values(crypto="BTC", time_ms=1, side="buy", qty="0.5", price="100")
        )
    engine.dispose()

    db = Database(path)
    db.init()
    with db.engine.connect() as conn:
        assert migrate.current(conn) == migrate.BASELINE
    with db.session() as s:
        assert s.query(HoldTxRow).one().qty == Decimal("0.5")
    assert _diffs(path) == []
    assert backup.validate(path) == migrate.BASELINE


def test_newer_base_is_refused(tmp_path):
    db = Database(tmp_path / "w.db")
    db.init()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("UPDATE alembic_version SET version_num = '9999'")
    with pytest.raises(migrate.SchemaError):
        Database(tmp_path / "w.db").init()
    with pytest.raises(backup.BackupError):
        backup.validate(tmp_path / "w.db")


def test_validate_legacy_file(tmp_path):
    path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(KV.__table__.insert().values(key="schema_version", value=1))
    assert backup.validate(path) == "0.x"


def test_backup_before_migration(tmp_path):
    db = Database(tmp_path / "w.db")
    db.init()
    with db.session() as s:
        s.add(Wallet(group_name="G", label="L", network="BTC", address="bc1qtest", created_ms=1))
    out = migrate._backup(db.path, "0001", "0002")
    assert out.parent.name == "backups" and "avant-migration-0001-vers-0002" in out.name
    con = sqlite3.connect(out)
    assert con.execute("SELECT count(*) FROM wallet").fetchone()[0] == 1
    con.close()


def test_files_are_private(tmp_path):
    db = Database(tmp_path / "data" / "w.db")
    db.init()
    assert stat.S_IMODE(db.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.path.parent.stat().st_mode) == 0o700


def test_baseline_guard():
    # Si ce test échoue, une migration a été ajoutée : figer dans migrate._baseline_tables le
    # schéma 0001 pour les bases 0.x, puis mettre à jour ce test.
    assert migrate.head() == migrate.BASELINE
