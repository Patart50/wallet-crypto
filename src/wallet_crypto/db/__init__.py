"""Base SQLite : un seul fichier dans le dossier de données. Sauvegarde = copier ce fichier."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import migrate
from .models import KV, SCHEMA_VERSION


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else None
        url = "sqlite://" if self.path is None else f"sqlite:///{self.path}"
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True)
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def init(self) -> str | None:
        """Crée ou migre le schéma (Alembic, D-034), protège le fichier, note la version.

        Renvoie le chemin de la copie faite avant une migration, le cas échéant.
        """
        saved = migrate.upgrade(self.engine, self.path)
        if self.path is not None:
            _private(self.path)
        with self.session() as s:
            if s.get(KV, "schema_version") is None:
                s.add(KV(key="schema_version", value=SCHEMA_VERSION))
        return saved

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._sessions()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()


def _private(path: Path) -> None:
    """Dossier de données en 700, base en 600 : le patrimoine n'est lisible que par son propriétaire."""
    try:
        path.parent.chmod(0o700)
        for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if p.exists():
                p.chmod(0o600)
    except OSError:  # système de fichiers sans droits Unix (partage Windows…) : sans effet
        pass


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")  # l'interface lit pendant qu'une sync écrit
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


__all__ = ["Database"]
