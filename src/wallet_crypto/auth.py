"""Mot de passe de l'interface (wallet D-010, D-021).

Obligatoire dès que le serveur écoute ailleurs que sur la machine locale : la page révèle tout
le patrimoine. Haché avec scrypt (bibliothèque standard), sel aléatoire ; comparaison en temps
constant. Le secret des sessions est généré une fois et gardé dans ``data/secret.key``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
from pathlib import Path

N, R, P = 2**14, 8, 1
MIN_LENGTH = 8


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"Mot de passe trop court ({MIN_LENGTH} caractères minimum).")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    try:
        _, salt_b64, dk_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(dk_b64)
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=len(expected))
    return hmac.compare_digest(dk, expected)


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def storage_secret(data_dir: Path) -> str:
    path = Path(data_dir) / "secret.key"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value
