"""Client HTTP commun aux sources : délais, reprises sur 429 / 5xx, JSON lu en ``Decimal``,
secrets masqués dans les erreurs. Aucune télémétrie : seules les API appelées par les sources
reçoivent des requêtes."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import requests

from .. import __version__
from ..security import mask_secret

RETRY_STATUS = {429, 500, 502, 503, 504}
log = logging.getLogger("wallet_crypto.http")


class HttpError(RuntimeError):
    """Erreur réseau ou HTTP, message déjà masqué."""


class Http:
    def __init__(self, secrets: list[str] | None = None, retries: int = 2, backoff: float = 1.5):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            f"wallet-crypto/{__version__} (+https://github.com/Patart50/wallet-crypto)"
        )
        self.secrets = [s for s in (secrets or []) if s]
        self.retries = retries
        self.backoff = backoff

    def _mask(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, mask_secret(s))
        return text

    def _request(self, method: str, url: str, timeout: float, **kw) -> Any:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self.session.request(method, url, timeout=timeout, **kw)
                if r.status_code in RETRY_STATUS and attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise HttpError(self._mask(f"HTTP {r.status_code} sur {url} : {r.text[:200]}"))
                return r.json(parse_float=Decimal)
            except HttpError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
        host = urlsplit(url).hostname or url
        log.debug("%s", self._mask(f"{method} {url} : {last!r}"))
        if isinstance(last, requests.Timeout):
            raise HttpError(f"{host} ne répond pas (délai dépassé)")
        if isinstance(last, requests.ConnectionError):
            raise HttpError(f"connexion impossible à {host} (réseau, pare-feu ou proxy)")
        raise HttpError(self._mask(f"réponse illisible de {host} : {last}"))

    def post_json(self, url: str, payload: Any, timeout: float = 30) -> Any:
        return self._request("POST", url, timeout, json=payload)

    def get_json(self, url: str, params: dict | None = None, timeout: float = 30) -> Any:
        return self._request("GET", url, timeout, params=params)
