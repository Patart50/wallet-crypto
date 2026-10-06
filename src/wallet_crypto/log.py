"""Journaux : ``data/logs/wallet-crypto.log``, avec masquage des secrets (wallet D-010).

La clé Alchemy figure dans les URL d'appel : elle est remplacée par une version masquée dans
chaque message, quel que soit le module qui journalise.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Config
from .security import mask_secret

LOGGER_NAME = "wallet_crypto"


class SecretFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            msg = record.getMessage()
            for s in self.secrets:
                msg = msg.replace(s, mask_secret(s))
            record.msg, record.args = msg, ()
        return True


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def setup_logging(config: Config, verbose: bool = False) -> logging.Logger:
    """Fichier tournant (5 × 2 Mo) + console. Idempotent."""
    config.ensure_dirs()
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)
    flt = SecretFilter(config.secrets)
    fh = RotatingFileHandler(
        config.log_dir / "wallet-crypto.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    fh.setLevel(logging.DEBUG)
    fh.addFilter(flt)
    root.addHandler(fh)
    if verbose:  # sinon la console n'affiche que le résumé de la commande
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
        ch.setLevel(logging.DEBUG)
        ch.addFilter(flt)
        root.addHandler(ch)
    root.propagate = False
    return root
