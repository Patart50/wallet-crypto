"""Garde-fous de saisie (wallet D-005).

L'outil est en lecture seule : il n'accepte que des adresses publiques. Tout ce qui ressemble
à une clé privée ou à une phrase de récupération est refusé, avec un message qui explique
pourquoi. Les adresses sont aussi contrôlées par réseau, pour attraper les erreurs de copie.
"""

from __future__ import annotations

import re

_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")
_WORD = re.compile(r"^[a-zA-Z]+$")

SECRET_MESSAGE = (
    "Ceci ressemble à une clé privée ou à une phrase de récupération. wallet-crypto ne les "
    "demande jamais : il lit uniquement des adresses publiques. Ne communiquez cette donnée à "
    "personne, et si vous l'avez collée ailleurs par erreur, transférez vos fonds vers un "
    "nouveau wallet."
)

NETWORKS = ("HL", "EVM", "SOL", "BTC")


class InputRejected(ValueError):
    """Saisie refusée ; le message est destiné à l'utilisateur."""


def looks_like_secret(value: str) -> bool:
    """Clé privée (hexadécimale, WIF, Solana, xprv) ou phrase mnémonique de 12 à 24 mots."""
    v = (value or "").strip()
    if not v:
        return False
    if _HEX64.match(v):
        return True
    words = v.split()
    if len(words) in (12, 15, 18, 21, 24) and all(_WORD.match(w) for w in words):
        return True
    if v.startswith(("xprv", "yprv", "zprv", "tprv")) and len(v) > 100:
        return True
    if _BASE58.match(v):
        # WIF Bitcoin (51 ou 52 caractères, commence par 5, K ou L) ; clé Solana (87-88 car.)
        if len(v) in (51, 52) and v[0] in "5KL":
            return True
        if len(v) in (87, 88):
            return True
    return False


_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values: list[int]) -> int:
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def bech32_valid(address: str) -> bool:
    """Checksum bech32 (segwit v0) ou bech32m (taproot)."""
    a = address.strip()
    if a.lower() != a and a.upper() != a:
        return False
    a = a.lower()
    sep = a.rfind("1")
    if sep < 1 or sep + 7 > len(a) or len(a) > 90:
        return False
    hrp, data = a[:sep], a[sep + 1 :]
    if any(c not in _BECH32 for c in data):
        return False
    values = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + [_BECH32.index(c) for c in data]
    return _bech32_polymod(values) in (1, 0x2BC830A3)


def normalize_address(network: str, address: str) -> str:
    """Contrôle et normalise une adresse publique ; lève ``InputRejected`` sinon."""
    net = (network or "").upper().strip()
    a = (address or "").strip()
    if net not in NETWORKS:
        raise InputRejected(f"Réseau inconnu : {network!r}. Réseaux pris en charge : {', '.join(NETWORKS)}.")
    if looks_like_secret(a):
        raise InputRejected(SECRET_MESSAGE)
    if net == "HL" and a.lower().startswith("hl:"):
        a = a[3:].strip()
    if net in ("HL", "EVM"):
        if not _EVM.match(a):
            raise InputRejected("Adresse attendue au format 0x suivi de 40 caractères hexadécimaux.")
        return a.lower()
    if net == "BTC":
        if a.lower().startswith(("bc1", "tb1")):
            if not bech32_valid(a):
                raise InputRejected("Adresse Bitcoin bech32 invalide (somme de contrôle incorrecte).")
            return a.lower()
        if a[:1] in ("1", "3") and _BASE58.match(a) and 26 <= len(a) <= 35:
            return a
        if a.startswith(("xpub", "ypub", "zpub")):
            raise InputRejected(
                "Les clés étendues (xpub) ne sont pas prises en charge : saisissez une adresse."
            )
        raise InputRejected("Adresse Bitcoin invalide.")
    # SOL
    if not (_BASE58.match(a) and 32 <= len(a) <= 44):
        raise InputRejected("Adresse Solana invalide (32 à 44 caractères base58).")
    return a


def mask_secret(value: str | None, keep: int = 4) -> str:
    """Masque une clé pour l'affichage : « abcd…wxyz »."""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "…"
    return f"{value[:keep]}…{value[-keep:]}"
