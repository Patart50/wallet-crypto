"""Prix publics Binance (aucune clé) : cours du jour et bougies historiques.

Mêmes hôtes que les autres outils du programme : ``data-api.binance.vision`` (données de
marché, accessible sans restriction géographique) puis ``api.binance.com``. Seuls des noms de
paires et des dates sont envoyés.

Cours en USD : paire ``XUSDT``, sinon ``XUSDC``, sinon ``XFDUSD``, sinon ``XBTC × BTCUSDT``.
USDT et USDC sont assimilés au dollar. Taux EUR : ``1 ÷ EURUSDT``.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from ..money import D

log = logging.getLogger("wallet_crypto.sources.binance")

HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
USD_QUOTES = ("USDT", "USDC", "FDUSD")


def fetch_ticker(http) -> dict[str, Decimal]:
    """Tous les cours en une requête (``/api/v3/ticker/price``)."""
    last: Exception | None = None
    for host in HOSTS:
        try:
            rows = http.get_json(f"{host}/api/v3/ticker/price", timeout=20)
            return parse_ticker(rows)
        except Exception as exc:
            last = exc
            log.warning("Binance %s : %s", host, exc)
    raise RuntimeError(f"Binance injoignable : {last}")


def parse_ticker(rows) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for r in rows or []:
        try:
            p = D(r.get("price"))
        except ValueError:
            continue
        if p > 0 and r.get("symbol"):
            out[str(r["symbol"]).upper()] = p
    return out


def price_usd(ticker: dict[str, Decimal], base: str) -> tuple[Decimal | None, str]:
    """(cours en USD, chemin utilisé) ou (None, '')."""
    b = (base or "").upper()
    for q in USD_QUOTES:
        p = ticker.get(f"{b}{q}")
        if p:
            return p, f"{b}{q}"
    via = ticker.get(f"{b}BTC")
    btc = ticker.get("BTCUSDT")
    if via and btc:
        return via * btc, f"{b}BTC × BTCUSDT"
    return None, ""


def eur_per_usd(ticker: dict[str, Decimal]) -> Decimal | None:
    """Euros pour un dollar (USDT assimilé), pour l'affichage en euros."""
    p = ticker.get("EURUSDT")
    return (Decimal(1) / p) if p else None


def parse_klines(rows) -> list[tuple[int, Decimal]]:
    """Bougies ``/api/v3/klines`` → [(heure d'ouverture ms, clôture)]."""
    out = []
    for r in rows or []:
        try:
            out.append((int(r[0]), D(r[4])))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def fetch_klines(http, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000):
    last: Exception | None = None
    for host in HOSTS:
        try:
            rows = http.get_json(
                f"{host}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": limit,
                },
                timeout=20,
            )
            return parse_klines(rows)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"Binance klines {symbol} : {last}")
