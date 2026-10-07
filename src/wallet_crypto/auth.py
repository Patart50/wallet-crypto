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


def session_token(secret: str, material: str) -> str:
    """Jeton de session lié au mot de passe en vigueur (wallet D-035).

    Changer ou supprimer le mot de passe change le jeton : les sessions ouvertes avant sont
    déconnectées. Pour la variable d'environnement, ``material`` est le mot de passe lui-même
    (son hachage change à chaque démarrage, à cause du sel).
    """
    return hmac.new(secret.encode(), material.encode(), hashlib.sha256).hexdigest()


def host_header_is_loopback(host: str) -> bool:
    """``Host`` d'une requête (``127.0.0.1:8090``, ``localhost``, ``[::1]:8090``) local ?"""
    host = (host or "").strip().lower()
    if host.startswith("["):
        name = host[1 : host.find("]")] if "]" in host else host[1:]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name != "" and is_loopback(name)


class LoginThrottle:
    """Freinage des essais de mot de passe, global au serveur (toutes connexions confondues).

    Après ``free`` échecs, chaque nouvel échec bloque la connexion pendant une durée qui double
    (30 s, 60 s, … jusqu'à 15 min). Une connexion réussie remet le compteur à zéro.
    """

    def __init__(self, free: int = 5, base_s: float = 30, max_s: float = 900):
        self.free, self.base_s, self.max_s = free, base_s, max_s
        self.failures = 0
        self.until = 0.0

    def wait_s(self, now: float) -> float:
        return max(0.0, self.until - now)

    def failed(self, now: float) -> None:
        self.failures += 1
        if self.failures >= self.free:
            self.until = now + min(self.base_s * 2 ** (self.failures - self.free), self.max_s)

    def succeeded(self) -> None:
        self.failures = 0
        self.until = 0.0
