"""Réglages modifiables depuis l'interface, enregistrés dans la base (table ``kv``).

Priorité : variable d'environnement (ou ``.env``) > réglage enregistré > valeur par défaut.
Une clé Alchemy définie dans l'environnement verrouille le réglage dans l'interface : c'est
l'administrateur de la machine qui décide.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from .config import Config
from .db import Database, store
from .log import add_secret

CURRENCIES = ("USD", "EUR")
THEMES = ("dark", "light")
KEYS = {"alchemy_key", "currency", "theme", "sync_hours", "password_hash"}


@dataclass
class Settings:
    alchemy_key: str
    alchemy_from_env: bool
    currency: str
    theme: str
    sync_hours: float
    password_hash: str | None


def load_settings(db: Database, config: Config) -> Settings:
    with db.session() as s:
        kv = {k: store.kv_get(s, k) for k in KEYS}
    currency = kv["currency"] if kv["currency"] in CURRENCIES else "USD"
    theme = kv["theme"] if kv["theme"] in THEMES else "dark"
    try:
        hours = float(kv["sync_hours"]) if kv["sync_hours"] else config.sync_hours
    except (TypeError, ValueError):
        hours = config.sync_hours
    return Settings(
        alchemy_key=config.alchemy_key or (kv["alchemy_key"] or ""),
        alchemy_from_env=bool(config.alchemy_key),
        currency=currency,
        theme=theme,
        sync_hours=min(max(hours, 0.25), 48.0),
        password_hash=kv["password_hash"] or None,
    )


def save_setting(db: Database, key: str, value: Any) -> None:
    if key not in KEYS:
        raise ValueError(f"Réglage inconnu : {key}")
    if key == "currency" and value not in CURRENCIES:
        raise ValueError(f"Devise inconnue : {value}")
    if key == "theme" and value not in THEMES:
        raise ValueError(f"Thème inconnu : {value}")
    if key == "sync_hours":
        value = min(max(float(value), 0.25), 48.0)
    if key == "alchemy_key":
        value = (value or "").strip()
        add_secret(value)
    with db.session() as s:
        store.kv_set(s, key, value)


def effective_config(db: Database, config: Config) -> Config:
    """Configuration complétée par les réglages enregistrés (clé Alchemy, fréquence)."""
    st = load_settings(db, config)
    add_secret(st.alchemy_key)
    return dataclasses.replace(config, alchemy_key=st.alchemy_key, sync_hours=st.sync_hours)
