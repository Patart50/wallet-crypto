"""Lignes d'actifs d'un wallet et leur valorisation.

Une ligne = un actif tel qu'il existe réellement dans un wallet après une synchronisation.
Les suffixes distinguent les états d'un même token :

- ``HYPE_STAKED``, ``WCT_STAKED`` : staké (n'est plus dans le solde libre) ;
- ``WCT_PENDING`` : récompenses réclamables ;
- ``USDC_SPOT``, ``USDT_SPOT`` : soldes spot Hyperliquid d'un compte standard ;
- ``HLP_VAULTS`` : parts de vaults Hyperliquid, valorisées en USD.

Une seule fonction valorise une ligne (``line_value``) : la barre de patrimoine, les snapshots
et les onglets s'en servent tous, ce qui garantit le même total partout (wallet D-006).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..money import EPS, ONE, ZERO

PriceFn = Callable[[str], Decimal | None]

STABLES = frozenset(
    {
        "USDC", "USDT", "DAI", "USDE", "USDH", "USDT0", "FDUSD", "PYUSD", "USDS", "TUSD",
        "USDC.E", "USDBC", "USD1", "USDB", "LUSD", "GHO", "CRVUSD", "FRAX",
    }
)  # fmt: skip
_SUFFIXES = ("_STAKED", "_PENDING", "_SPOT")


@dataclass
class AssetLine:
    """Un actif dans un wallet.

    ``val`` : valeur en USD fournie par la source (Alchemy, ligne USDC Hyperliquid) ; ``None``
    si la source ne donne pas de prix (le prix est alors appliqué à la valorisation).
    ``px_sync`` : prix noté au moment de la synchronisation, repli si aucun prix courant.
    ``extra`` : détails propres à la source (marge, positions, fin du lock…), non calculés.
    """

    coin: str
    qty: Decimal
    val: Decimal | None = None
    src: str = ""
    px_sync: Decimal | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def asset_base(coin: str) -> str:
    """``WCT_STAKED`` → ``WCT`` ; ``USDC_SPOT`` → ``USDC`` ; ``HLP_VAULTS`` → ``USDC``."""
    c = str(coin or "").upper()
    if c.startswith("HLP_"):
        return "USDC"
    for suf in _SUFFIXES:
        if c.endswith(suf):
            return c[: -len(suf)]
    return c


def asset_category(coin: str) -> str:
    """``stake`` (staké, réclamable, vaults) | ``liquid`` (stablecoins) | ``hold`` (le reste)."""
    c = str(coin or "").upper()
    if c == "HLP_VAULTS" or c.endswith(("_STAKED", "_PENDING")):
        return "stake"
    if asset_base(c) in STABLES:
        return "liquid"
    return "hold"


def is_stable(base: str) -> bool:
    return str(base or "").upper() in STABLES


@dataclass(frozen=True)
class Valuation:
    qty: Decimal
    price: Decimal
    value: Decimal
    unpriced: bool


def line_value(
    line: AssetLine, price_fn: PriceFn | None = None, fallback_fn: PriceFn | None = None
) -> Valuation:
    """Valeur USD d'une ligne.

    Priorité du prix : valeur de la source > stablecoin = 1 > prix courant (``price_fn``)
    > prix de la synchronisation (``px_sync``) > prix en cache (``fallback_fn``).
    Sans prix : ``unpriced`` et valeur nulle (signalé, jamais compté au hasard).
    """
    qty = line.qty
    if qty <= EPS:
        return Valuation(qty, ZERO, ZERO, False)
    if line.val is not None:
        return Valuation(qty, line.val / qty, line.val, False)
    base = asset_base(line.coin)
    if base in STABLES:
        return Valuation(qty, ONE, qty, False)
    p = price_fn(base) if price_fn else None
    if not p and line.px_sync:
        p = line.px_sync
    if not p and fallback_fn:
        p = fallback_fn(base)
    if not p:
        return Valuation(qty, ZERO, ZERO, True)
    return Valuation(qty, p, qty * p, False)
