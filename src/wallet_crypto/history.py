"""Prix historiques : clôtures journalières mises en cache dans SQLite (wallet D-022).

Servent à valoriser dans le temps ce qui n'a pas de valeur en dollars au moment où cela
arrive : récompenses de staking (au cours du jour de réception) et inventaire du hold (gains
cumulés jour par jour).

- Mise à jour **pendant la synchronisation seulement** : l'interface lit le cache, elle
  n'appelle jamais le réseau.
- Source par actif : Binance (``XUSDT``, sinon ``XUSDC``) ; sinon bougies Hyperliquid
  (``candleSnapshot``, utile pour HYPE et les actifs propres à Hyperliquid).
- Une bougie = un jour UTC ; sa clôture vaut pour tout instant de ce jour. Approximation
  assumée : à l'échelle de gains cumulés sur des semaines, l'écart intra-journalier est
  négligeable devant les variations d'un jour à l'autre.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .core.assets import STABLES
from .db.models import HlFill, HoldTxRow, KlineCache, ManualStakeRow, ManualStakeTxRow, StakeEventRow
from .money import ONE, D
from .sources import binance, hyperliquid

log = logging.getLogger("wallet_crypto.history")

DAY_MS = 86_400_000
MAX_GAP_DAYS = 3  # au-delà, pas de prix plutôt qu'un prix périmé
BINANCE_PAGE = 1000
HL_PAGE_DAYS = 4000


def day_start(ms: int) -> int:
    return ms - ms % DAY_MS


def needed_assets(s: Session, spot_pairs: dict[str, dict]) -> dict[str, int]:
    """{actif : premier instant où son prix est utile}. Achats et ventes du hold (saisis ou
    spot Hyperliquid), récompenses de staking (automatiques et saisies)."""
    out: dict[str, int] = {}

    def need(base: str, t: int | None) -> None:
        b = (base or "").upper()
        if not b or b in STABLES or t is None:
            return
        out[b] = min(out.get(b, t), t)

    for crypto, t in s.execute(
        select(HoldTxRow.crypto, func.min(HoldTxRow.time_ms)).group_by(HoldTxRow.crypto)
    ):
        need(crypto, t)
    for coin, t in s.execute(
        select(HlFill.coin, func.min(HlFill.time_ms)).where(HlFill.is_spot.is_(True)).group_by(HlFill.coin)
    ):
        pair = spot_pairs.get(coin)
        if pair:
            need(pair["base"], t)
    for asset, t in s.execute(
        select(StakeEventRow.asset, func.min(StakeEventRow.time_ms)).group_by(StakeEventRow.asset)
    ):
        need(asset, t)
    for crypto, t in s.execute(
        select(ManualStakeRow.crypto, func.min(ManualStakeTxRow.time_ms))
        .join(ManualStakeTxRow, ManualStakeTxRow.position_id == ManualStakeRow.id)
        .group_by(ManualStakeRow.crypto)
    ):
        need(crypto, t)
    return out


def choose_symbol(base: str, ticker: dict[str, Decimal], hl_mids: dict[str, Decimal]) -> str | None:
    """Clé de cache : ``BINANCE:HYPEUSDT`` ou ``HL:HYPE``."""
    for q in ("USDT", "USDC"):
        if f"{base}{q}" in ticker:
            return f"BINANCE:{base}{q}"
    if base in hl_mids:
        return f"HL:{base}"
    return None


def parse_hl_candles(rows) -> list[tuple[int, Decimal]]:
    out = []
    for r in rows or []:
        try:
            out.append((int(r["t"]), D(r["c"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetch_candles(http, key: str, start_ms: int, end_ms: int) -> list[tuple[int, Decimal]]:
    source, _, symbol = key.partition(":")
    out: list[tuple[int, Decimal]] = []
    if source == "BINANCE":
        cur = start_ms
        while cur <= end_ms:
            batch = binance.fetch_klines(http, symbol, "1d", cur, end_ms, BINANCE_PAGE)
            if not batch:
                break
            out += batch
            cur = batch[-1][0] + DAY_MS
            if len(batch) < BINANCE_PAGE:
                break
        return out
    if source == "HL":
        cur = start_ms
        while cur <= end_ms:
            stop = min(end_ms, cur + HL_PAGE_DAYS * DAY_MS)
            rows = http.post_json(
                hyperliquid.API,
                {
                    "type": "candleSnapshot",
                    "req": {"coin": symbol, "interval": "1d", "startTime": cur, "endTime": stop},
                },
                timeout=20,
            )
            out += parse_hl_candles(rows)
            cur = stop + DAY_MS
        return out
    raise ValueError(f"source de bougies inconnue : {key}")


def update_cache(s: Session, http, ticker, hl_mids, spot_pairs, now_ms: int) -> dict[str, str]:
    """Complète le cache pour chaque actif utile. Renvoie {actif : clé} (enregistré en kv).
    Un actif sans source reste sans historique : il est signalé, jamais inventé."""
    from .db import store

    symbols: dict[str, str] = dict(store.kv_get(s, "kline_symbols", {}) or {})
    for base, first in needed_assets(s, spot_pairs).items():
        key = symbols.get(base) or choose_symbol(base, ticker, hl_mids)
        if not key:
            log.info("Pas de source de prix historique pour %s", base)
            continue
        symbols[base] = key
        last = s.scalar(select(func.max(KlineCache.day_ms)).where(KlineCache.symbol == key))
        earliest = s.scalar(select(func.min(KlineCache.day_ms)).where(KlineCache.symbol == key))
        ranges = []
        if earliest is None:
            ranges.append((day_start(first) - DAY_MS, now_ms))
        else:
            if day_start(first) - DAY_MS < earliest:
                ranges.append((day_start(first) - DAY_MS, earliest - DAY_MS))
            ranges.append((last, now_ms))  # la bougie du jour est rafraîchie
        try:
            for start, end in ranges:
                for day, close in fetch_candles(http, key, start, end):
                    row = s.get(KlineCache, (key, day))
                    if row is None:
                        s.add(KlineCache(symbol=key, day_ms=day, close=close))
                    else:
                        row.close = close
                s.flush()
        except Exception as exc:
            log.warning("Bougies %s (%s) : %s", base, key, exc)
    store.kv_set(s, "kline_symbols", symbols)
    return symbols


class HistoricalPrices:
    """``prix(actif, t)`` : clôture du jour UTC de ``t`` (ou du dernier jour connu, à trois
    jours près), lue dans le cache ; jamais d'appel réseau. Pour un instant récent (moins d'un
    jour), le prix courant prime : ``current_fn`` (prix rafraîchis par le serveur), sinon le
    dernier prix enregistré à la synchronisation. Les stablecoins valent 1. ``missing`` liste
    les actifs demandés sans historique."""

    def __init__(self, db, now_ms: int, current_fn=None):
        from .db import store
        from .db.models import PriceCache

        self.now_ms = now_ms
        self.current_fn = current_fn
        self.missing: set[str] = set()
        with db.session() as s:
            self.cached = {r.base: r.price for r in s.scalars(select(PriceCache))}
            self.symbols: dict[str, str] = dict(store.kv_get(s, "kline_symbols", {}) or {})
            self.series: dict[str, tuple[list[int], list[Decimal]]] = {}
            for key in set(self.symbols.values()):
                rows = s.execute(
                    select(KlineCache.day_ms, KlineCache.close)
                    .where(KlineCache.symbol == key)
                    .order_by(KlineCache.day_ms)
                ).all()
                self.series[key] = ([r[0] for r in rows], [r[1] for r in rows])

    def current(self, base: str) -> Decimal | None:
        p = self.current_fn(base) if self.current_fn else None
        return p or self.cached.get(base)

    def __call__(self, base: str, t: int) -> Decimal | None:
        b = (base or "").upper()
        if b in STABLES:
            return ONE
        if t >= self.now_ms - DAY_MS:
            p = self.current(b)
            if p:
                return p
        key = self.symbols.get(b)
        days, closes = self.series.get(key, ([], [])) if key else ([], [])
        if not days:
            self.missing.add(b)
            return None
        i = bisect_right(days, t) - 1
        if i < 0 or t - days[i] > MAX_GAP_DAYS * DAY_MS:
            return None
        return closes[i]
