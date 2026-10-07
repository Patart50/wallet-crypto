"""Export et import de la base (sauvegarde complète, wallet D-025).

L'export est une copie cohérente du fichier SQLite (API de sauvegarde de SQLite), même pendant
qu'une synchronisation écrit. L'import vérifie que le fichier est bien une base wallet-crypto
d'une version prise en charge, garde une copie de la base actuelle dans ``data/backups/``,
puis la remplace.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from .db import Database
from .db.models import SCHEMA_VERSION


class BackupError(ValueError):
    pass


def export_bytes(db: Database) -> bytes:
    if db.path is None:
        raise BackupError("Base en mémoire : rien à exporter.")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "export.db"
        src = sqlite3.connect(db.path)
        dst = sqlite3.connect(out)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return out.read_bytes()


def validate(path: Path) -> int:
    """Renvoie la version de schéma, ou lève ``BackupError``."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM kv WHERE key = 'schema_version'").fetchone()
            con.execute("SELECT count(*) FROM wallet").fetchone()
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError("Ce fichier n'est pas une sauvegarde wallet-crypto.") from exc
    if not row:
        raise BackupError("Version de la sauvegarde introuvable.")
    version = int(str(row[0]).strip('"'))
    if version > SCHEMA_VERSION:
        raise BackupError(
            "Sauvegarde créée par une version plus récente de wallet-crypto : mettez l'outil à jour."
        )
    return version


def import_bytes(db: Database, data: bytes) -> Path:
    """Remplace la base par ``data``. Renvoie le chemin de la copie de l'ancienne base."""
    if db.path is None:
        raise BackupError("Base en mémoire : import impossible.")
    with tempfile.TemporaryDirectory() as tmp:
        incoming = Path(tmp) / "incoming.db"
        incoming.write_bytes(data)
        validate(incoming)
        backups = db.path.parent / "backups"
        backups.mkdir(exist_ok=True)
        keep = backups / f"avant-import-{time.strftime('%Y%m%d-%H%M%S')}.db"
        keep.write_bytes(export_bytes(db))
        db.engine.dispose()
        for suffix in ("-wal", "-shm"):
            Path(str(db.path) + suffix).unlink(missing_ok=True)
        shutil.copyfile(incoming, db.path)
    db.init()
    return keep
