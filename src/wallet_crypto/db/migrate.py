"""Migrations du schéma (wallet D-018, D-034).

Au démarrage, ``Database.init`` amène la base à la dernière révision :

- base vide : toutes les migrations sont jouées ;
- base créée par une version 0.x (sans table ``alembic_version``) : les tables manquantes sont
  créées comme avant, puis la base est marquée au schéma initial ``0001``, qui est exactement
  celui des versions 0.x ;
- base en retard : une copie est gardée dans ``backups/avant-migration-*.db``, puis les
  migrations manquantes sont jouées.

Une base plus récente que l'outil (révision inconnue) est refusée : il faut mettre l'outil à jour.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from .models import Base

log = logging.getLogger("wallet_crypto.db")

MIGRATIONS = Path(__file__).parent / "migrations"
BASELINE = "0001"


class SchemaError(RuntimeError):
    """Base inutilisable par cette version de l'outil."""


def _config(connection: Connection | None = None) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def script() -> ScriptDirectory:
    return ScriptDirectory.from_config(_config())


def head() -> str:
    return script().get_current_head()


def known(revision: str) -> bool:
    try:
        return script().get_revision(revision) is not None
    except Exception:  # révision absente du dossier : base plus récente que l'outil
        return False


def current(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def upgrade(engine: Engine, db_path: Path | None) -> str | None:
    """Amène la base à la dernière révision. Renvoie le chemin de la copie faite avant, le cas échéant."""
    target = head()
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        rev = current(conn) if "alembic_version" in tables else None

    if not tables:
        _run(engine, lambda cfg: command.upgrade(cfg, "head"))
        return None

    if rev is None:  # base 0.x
        Base.metadata.create_all(engine, tables=_baseline_tables())
        _run(engine, lambda cfg: command.stamp(cfg, BASELINE))
        rev = BASELINE

    if rev == target:
        return None
    if not known(rev):
        raise SchemaError(
            f"Base créée par une version plus récente de wallet-crypto (schéma {rev}) : mettez l'outil à jour."
        )
    saved = _backup(db_path, rev, target)
    log.warning("Migration du schéma %s → %s (copie avant migration : %s)", rev, target, saved)
    _run(engine, lambda cfg: command.upgrade(cfg, "head"))
    return str(saved) if saved else None


def _baseline_tables():
    # Les bases 0.x ont été créées par ``create_all`` sur des modèles identiques au schéma 0001.
    # Valable tant que les modèles n'ont pas changé : la première migration qui modifie une table
    # existante devra figer ici la description des tables de 0001 (garde-fou dans les tests).
    return list(Base.metadata.sorted_tables)


def _run(engine: Engine, fn) -> None:
    with engine.begin() as conn:
        fn(_config(conn))


def _backup(db_path: Path | None, rev: str, target: str) -> Path | None:
    if db_path is None or not db_path.is_file():
        return None
    folder = db_path.parent / "backups"
    folder.mkdir(exist_ok=True)
    out = folder / f"avant-migration-{rev}-vers-{target}-{time.strftime('%Y%m%d-%H%M%S')}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return out
