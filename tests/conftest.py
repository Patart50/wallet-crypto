"""Outils de test communs. Toutes les données sont fictives (aucune adresse ni montant réel)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from wallet_crypto.money import loads

FIXTURES = Path(__file__).parent / "fixtures"

# Adresses fictives, générées pour les tests : elles n'appartiennent à personne de connu.
ADDR_HL = "0x1111111111111111111111111111111111111111"
ADDR_HL_BOT = "0x2222222222222222222222222222222222222222"
ADDR_EVM = "0x3333333333333333333333333333333333333333"
ADDR_SOL = "So1aNaTestAddre55111111111111111111111111"
ADDR_BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"  # adresse d'exemple de la BIP-173


def fixture(name: str):
    return loads((FIXTURES / name).read_text(encoding="utf-8"))


def d(x) -> Decimal:
    return Decimal(str(x))


class FakeHttp:
    """Remplace le client HTTP : routes → réponse JSON (ou exception)."""

    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict | None]] = []
        self.post_routes: list[tuple] = []
        self.get_routes: list[tuple] = []

    def on_post(self, url_part: str, match: dict | None, response):
        self.post_routes.append((url_part, match or {}, response))
        return self

    def on_get(self, url_part: str, response):
        self.get_routes.append((url_part, response))
        return self

    @staticmethod
    def _resolve(response, payload):
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(payload)
        return (
            json.loads(json.dumps(response, default=str), parse_float=Decimal)
            if not isinstance(response, (str, int))
            else response
        )

    def post_json(self, url, payload, timeout=30):
        self.posts.append((url, payload))
        for part, match, resp in self.post_routes:
            if part in url and all(payload.get(k) == v for k, v in match.items()):
                return self._resolve(resp, payload)
        raise AssertionError(f"POST non prévu : {url} {payload}")

    def get_json(self, url, params=None, timeout=30):
        self.gets.append((url, params))
        for part, resp in self.get_routes:
            if part in url:
                return self._resolve(resp, params)
        raise AssertionError(f"GET non prévu : {url}")


@pytest.fixture
def http():
    return FakeHttp()
