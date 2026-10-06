"""Base SQLite : un seul fichier dans le dossier de données. Sauvegarde = copier ce fichier."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import KV, SCHEMA_VERSION, Base


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else None
        url = "sqlite://" if self.path is None else f"sqlite:///{self.path}"
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(url, future=True)
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def init(self) -> None:
        """Crée les tables manquantes (sans toucher aux existantes) et note la version."""
        Base.metadata.create_all(self.engine)
        with self.session() as s:
            if s.get(KV, "schema_version") is None:
                s.add(KV(key="schema_version", value=SCHEMA_VERSION))

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


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")  # l'interface lit pendant qu'une sync écrit
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


__all__ = ["Database"]
