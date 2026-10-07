"""État partagé du serveur : base, configuration, prix courants, synchronisation en cours."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from .. import auth
from ..config import Config
from ..db import Database
from ..prices import MarketPrices
from ..settings import Settings, effective_config, load_settings
from ..sources.http import Http

log = logging.getLogger("wallet_crypto.ui")

PRICE_TTL_S = 30 * 60  # au-delà, les prix courants ne sont plus utilisés (repli : dernière sync)


@dataclass
class PriceBoard:
    """Prix courants rafraîchis toutes les 5 minutes par le serveur (D-024)."""

    market: MarketPrices | None = None
    loaded_at: float = 0.0

    def fresh(self) -> bool:
        return self.market is not None and time.time() - self.loaded_at < PRICE_TTL_S

    def usd(self, base: str) -> Decimal | None:
        if not self.fresh():
            return None
        p = self.market.usd(base)
        return p

    def eur_per_usd(self) -> Decimal | None:
        return self.market.eur_per_usd() if self.fresh() else None

    def refresh(self, http) -> None:
        m = MarketPrices.load(http)
        if m.ticker or m.hl_mids:
            self.market = m
            self.loaded_at = time.time()


@dataclass
class AppContext:
    db: Database
    base_config: Config
    demo: bool = False
    env_password_hash: str | None = None
    env_password_token: str | None = None
    secret: str = ""
    exposed: bool = False  # écoute hors boucle locale (hors Docker) : mot de passe obligatoire
    prices: PriceBoard = field(default_factory=PriceBoard)
    syncing: bool = False
    last_sync_report: object | None = None
    gains_cache: dict = field(default_factory=dict)
    version: int = 0  # incrémenté à chaque changement de données (rafraîchit les pages ouvertes)

    @property
    def config(self) -> Config:
        return effective_config(self.db, self.base_config)

    @property
    def settings(self) -> Settings:
        return load_settings(self.db, self.base_config)

    def http(self) -> Http:
        return Http(self.config.secrets)

    def price_fn(self):
        return self.prices.usd if self.prices.fresh() else None

    def password_hash(self) -> str | None:
        return self.env_password_hash or self.settings.password_hash

    def auth_token(self) -> str | None:
        """Jeton attendu dans la session ; ``None`` sans mot de passe (D-035)."""
        if self.env_password_token:
            return self.env_password_token
        h = self.settings.password_hash
        return auth.session_token(self.secret, h) if h else None

    def bump(self) -> None:
        self.version += 1
        self.gains_cache.clear()


CTX: AppContext | None = None


def ctx() -> AppContext:
    if CTX is None:
        raise RuntimeError("Serveur non initialisé")
    return CTX
