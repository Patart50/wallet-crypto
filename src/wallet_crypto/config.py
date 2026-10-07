"""Configuration : variables d'environnement, fichier ``.env``, dossier de données.

Ordre de priorité : variables d'environnement > ``.env`` du dossier courant > valeurs par
défaut. La clé Alchemy saisie dans les Réglages (J2) sera enregistrée dans la base et prendra
le relais si l'environnement n'en fournit pas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Europe/Paris"
DEFAULT_SYNC_HOURS = 6


def load_dotenv(path: Path) -> dict[str, str]:
    """Lecteur minimal de ``.env`` (CLÉ=valeur, commentaires #, guillemets facultatifs).
    N'écrase jamais une variable déjà définie dans l'environnement."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip().removeprefix("export ").strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values


@dataclass
class Config:
    data_dir: Path
    alchemy_key: str = ""
    tz_name: str = DEFAULT_TZ
    sync_hours: float = DEFAULT_SYNC_HOURS
    password: str = ""  # mot de passe de l'interface (WALLET_CRYPTO_PASSWORD), en clair : jamais journalisé

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.tz_name)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wallet-crypto.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "sync.lock"

    @property
    def secrets(self) -> list[str]:
        """Valeurs à masquer dans les journaux et les messages d'erreur."""
        return [s for s in (self.alchemy_key, self.password) if s]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


def load_config(env: dict[str, str] | None = None, cwd: Path | None = None) -> Config:
    cwd = cwd or Path.cwd()
    merged = load_dotenv(cwd / ".env")
    merged.update(env if env is not None else os.environ)
    try:
        hours = float(merged.get("WALLET_CRYPTO_SYNC_HOURS") or DEFAULT_SYNC_HOURS)
    except ValueError:
        hours = DEFAULT_SYNC_HOURS
    data_dir = Path(merged.get("WALLET_CRYPTO_DATA") or (cwd / "data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = cwd / data_dir
    return Config(
        data_dir=data_dir,
        alchemy_key=(merged.get("ALCHEMY_API_KEY") or "").strip(),
        tz_name=merged.get("WALLET_CRYPTO_TZ") or DEFAULT_TZ,
        sync_hours=max(hours, 0.25),
        password=merged.get("WALLET_CRYPTO_PASSWORD") or "",
    )
