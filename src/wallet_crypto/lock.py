"""Verrou de fichier : jamais deux synchronisations en même temps (bouton, tâche
automatique, cron). Remplace le verrou Redis du module d'origine (wallet D-007).

Création atomique du fichier (``O_EXCL``), portable (Linux, macOS, Windows). Un verrou plus
vieux que ``stale_after`` secondes (sync interrompue brutalement) est considéré comme mort.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


class LockBusy(RuntimeError):
    pass


class FileLock:
    def __init__(self, path: Path, stale_after: float = 900):
        self.path = Path(path)
        self.stale_after = stale_after
        self.held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_after:
                    self.path.unlink(missing_ok=True)
                    continue
                raise LockBusy("Une synchronisation est déjà en cours.") from None
            with os.fdopen(fd, "w") as f:
                f.write(f"{os.getpid()} {int(time.time())}\n")
            self.held = True
            return
        raise LockBusy("Impossible de prendre le verrou de synchronisation.")

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
