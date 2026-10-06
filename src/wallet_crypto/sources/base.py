"""Interface commune des sources et registre (wallet D-014).

Une source sait lire, pour un réseau donné, les soldes d'une adresse et, si elle le peut, son
historique (fills, funding, mouvements de staking). Elle ne touche ni à la base ni à l'état
global : l'orchestrateur de synchronisation stocke ce qu'elle renvoie.

Ajouter une plateforme (Binance, Coinbase… plus tard) = écrire une classe ``Source`` et la
déclarer avec ``@register`` ; l'interface, la base et le patrimoine n'ont rien à changer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..core.assets import AssetLine


class SourceError(RuntimeError):
    """Échec d'une source ; message destiné à l'utilisateur (sans secret)."""


class MissingKey(SourceError):
    """Clé requise absente (ex. Alchemy)."""


@dataclass
class BalanceResult:
    lines: dict[str, AssetLine]
    positions: list[dict] | None = None
    keep_previous: tuple[str, ...] = ()  # lignes à reprendre de la sync précédente (lecture partielle)
    warnings: list[str] = field(default_factory=list)


@dataclass
class HistoryCursor:
    """Ce que la base contient déjà, pour n'importer que la suite."""

    last_fill_ms: int | None = None
    last_funding_ms: int | None = None
    known_sources: frozenset[str] = frozenset()  # sources de staking déjà présentes


@dataclass
class HistoryBatch:
    fills: list[dict] = field(default_factory=list)
    funding: list[dict] = field(default_factory=list)
    stake_events: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.fills) + len(self.funding) + len(self.stake_events)


class Source:
    network: ClassVar[str] = ""
    label: ClassVar[str] = ""
    needs_alchemy: ClassVar[bool] = False

    def __init__(self, http: Any, alchemy_key: str = ""):
        self.http = http
        self.alchemy_key = alchemy_key
        if self.needs_alchemy and not alchemy_key:
            raise MissingKey(
                f"{self.label} : clé Alchemy manquante. Ajoutez ALCHEMY_API_KEY dans le fichier .env "
                "(guide : README, « Obtenir votre clé Alchemy »)."
            )

    def fetch_balances(self, address: str, track_staking: bool = True) -> BalanceResult:
        raise NotImplementedError

    def fetch_history(self, address: str, track_staking: bool, cursor: HistoryCursor) -> HistoryBatch:
        return HistoryBatch()


REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    REGISTRY[cls.network] = cls
    return cls


def get_source(network: str, http: Any, alchemy_key: str = "") -> Source:
    cls = REGISTRY.get((network or "").upper())
    if cls is None:
        raise SourceError(f"Réseau non pris en charge : {network}")
    return cls(http, alchemy_key)


def add_line(lines: dict[str, AssetLine], coin: str, qty, val, src: str, chain: str | None = None) -> None:
    """Agrège un actif (même symbole sur plusieurs chaînes). ``val`` cumulée seulement si connue."""
    line = lines.get(coin)
    if line is None:
        line = lines[coin] = AssetLine(coin, qty * 0, None, src)
    line.qty += qty
    if val is not None:
        line.val = (line.val or 0) + val
    if chain:
        chains = line.extra.setdefault("chains", {})
        chains[chain] = chains.get(chain, 0) + qty
