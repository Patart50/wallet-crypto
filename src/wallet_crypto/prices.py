"""Prix courants en USD au moment d'une synchronisation.

Ordre : stablecoin = 1 ; Binance (``XUSDT``, ``XUSDC``, ``XFDUSD``, ``XBTC × BTCUSDT``) ;
prix médian Hyperliquid (``allMids``, perp puis paire spot) ; prix déduit d'une ligne Alchemy du
même token (ex. le WCT libre valorise le WCT staké). Chaque source manquante est tolérée.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from .core.assets import STABLES
from .sources import binance, hyperliquid

log = logging.getLogger("wallet_crypto.prices")

STABLE_QUOTES = ("USDC", "USDT0", "USDT", "USDH", "USDE")


class MarketPrices:
    def __init__(
        self,
        ticker: dict[str, Decimal] | None = None,
        hl_pairs: dict[str, dict] | None = None,
        hl_mids: dict[str, Decimal] | None = None,
    ):
        self.ticker = ticker or {}
        self.hl_pairs = hl_pairs or {}
        self.hl_mids = hl_mids or {}
        self.learned: dict[str, Decimal] = {}
        self.routes: dict[str, str] = {}
        self._spot_key: dict[str, str] = {}
        for name, p in self.hl_pairs.items():
            if p.get("quote") in STABLE_QUOTES:
                self._spot_key.setdefault(p["base"], name)

    @classmethod
    def load(cls, http) -> MarketPrices:
        try:
            ticker = binance.fetch_ticker(http)
        except Exception as exc:
            log.warning("Prix Binance indisponibles : %s", exc)
            ticker = {}
        pairs, mids = hyperliquid.load_market(http)
        return cls(ticker, pairs, mids)

    def learn(self, base: str, price: Decimal) -> None:
        """Prix déduit d'une ligne valorisée par la source (Alchemy)."""
        if price and price > 0:
            self.learned.setdefault(base.upper(), price)

    def usd(self, base: str) -> Decimal | None:
        b = (base or "").upper()
        if b in STABLES:
            return Decimal(1)
        p, route = binance.price_usd(self.ticker, b)
        if p:
            self.routes[b] = f"Binance {route}"
            return p
        mid = self.hl_mids.get(b) or self.hl_mids.get(self._spot_key.get(b, ""))
        if mid:
            self.routes[b] = "Hyperliquid"
            return mid
        if b in self.learned:
            self.routes[b] = "Alchemy"
            return self.learned[b]
        return None

    def eur_per_usd(self) -> Decimal | None:
        return binance.eur_per_usd(self.ticker)

    __call__ = usd
