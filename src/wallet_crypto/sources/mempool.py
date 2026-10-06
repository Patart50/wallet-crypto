"""Bitcoin : solde d'une adresse via mempool.space, aucune clé. Pas de clé étendue (xpub) en
v1.0 : une adresse = une ligne."""

from __future__ import annotations

from decimal import Decimal

from ..core.assets import AssetLine
from .base import BalanceResult, Source, SourceError, register

API = "https://mempool.space/api/address/{address}"


def parse_address(j: dict) -> Decimal:
    """Solde confirmé + transactions en attente, en BTC."""
    cs, ms = j.get("chain_stats") or {}, j.get("mempool_stats") or {}
    sats = (
        int(cs.get("funded_txo_sum", 0))
        - int(cs.get("spent_txo_sum", 0))
        + int(ms.get("funded_txo_sum", 0))
        - int(ms.get("spent_txo_sum", 0))
    )
    return Decimal(sats).scaleb(-8)


@register
class BitcoinSource(Source):
    network = "BTC"
    label = "Bitcoin (mempool.space)"

    def fetch_balances(self, address: str, track_staking: bool = True) -> BalanceResult:
        try:
            j = self.http.get_json(API.format(address=address.strip()), timeout=20)
        except Exception as exc:
            raise SourceError(f"mempool.space : {exc}") from exc
        qty = parse_address(j)
        lines = {"BTC": AssetLine("BTC", qty, None, "mempool")} if qty > 0 else {}
        return BalanceResult(lines)
