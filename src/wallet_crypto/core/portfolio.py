"""Patrimoine global sans double comptage (wallet D-006).

Règle : le total est la somme des lignes **réelles** des wallets ; chaque actif n'existe que
dans une ligne d'un wallet. Hold et Staking sont des vues de ces lignes, jamais ajoutées en
plus. Seul ajout possible : un staking manuel hors wallet (plateforme centralisée…), et
seulement si l'actif n'est pas déjà suivi automatiquement (sinon doublon probable : exclu et
signalé).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..money import EPS, ZERO
from .assets import AssetLine, PriceFn, asset_base, asset_category, line_value

CATEGORIES = ("liquid", "hold", "stake")


@dataclass
class WalletAssets:
    """Lignes d'un wallet. ``kind`` : ``auto`` (trading automatique), ``manuel`` (autre compte
    Hyperliquid) ou ``autres`` (wallets on-chain) — wallet D-011."""

    wallet_id: int
    label: str
    network: str
    lines: dict[str, AssetLine]
    kind: str = "autres"


@dataclass
class ManualStakeItem:
    """Staking manuel hors wallet, déjà valorisé."""

    id: int
    crypto: str
    qty: Decimal
    val: Decimal | None
    duplicate: bool = False


@dataclass
class PortfolioSummary:
    liquid: Decimal = ZERO
    hold: Decimal = ZERO
    stake: Decimal = ZERO
    manual: Decimal = ZERO
    by_coin: dict[str, dict] = field(default_factory=dict)
    by_wallet: dict[int, Decimal] = field(default_factory=dict)
    by_wallet_cat: dict[int, dict[str, Decimal]] = field(default_factory=dict)
    unpriced: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    n_wallets: int = 0

    @property
    def total(self) -> Decimal:
        return self.liquid + self.hold + self.stake + self.manual


def wallet_kind(network: str, auto_trading: bool) -> str:
    """Poste d'un wallet pour les graphiques : la case « trading automatique » (D-011)."""
    if (network or "").upper() != "HL":
        return "autres"
    return "auto" if auto_trading else "manuel"


def auto_stake_bases(wallets: list[WalletAssets]) -> set[str]:
    """Actifs dont le staking est suivi automatiquement (lignes ``_STAKED`` / ``_PENDING``)."""
    return {asset_base(c) for w in wallets for c in w.lines if c.upper().endswith(("_STAKED", "_PENDING"))}


def portfolio_summary(
    wallets: list[WalletAssets],
    price_fn: PriceFn | None = None,
    fallback_fn: PriceFn | None = None,
    manual_items: list[ManualStakeItem] | None = None,
) -> PortfolioSummary:
    out = PortfolioSummary()
    for w in wallets:
        out.n_wallets += 1
        wt = ZERO
        for coin, line in w.lines.items():
            v = line_value(line, price_fn, fallback_fn)
            if v.qty <= EPS:
                continue
            if v.unpriced:
                out.unpriced.append(f"{w.label}:{coin}")
                continue
            cat = asset_category(coin)
            setattr(out, cat, getattr(out, cat) + v.value)
            wt += v.value
            wc = out.by_wallet_cat.setdefault(w.wallet_id, dict.fromkeys(CATEGORIES, ZERO))
            wc[cat] += v.value
            key = coin.upper() if cat == "stake" else asset_base(coin)
            bc = out.by_coin.setdefault(key, {"qty": ZERO, "val": ZERO, "cat": cat})
            bc["qty"] += v.qty
            bc["val"] += v.value
        out.by_wallet[w.wallet_id] = wt
    for m in manual_items or []:
        if m.duplicate:
            out.duplicates.append(m.crypto)
            continue
        if m.val is None:
            out.unpriced.append(f"staking manuel:{m.crypto}")
            continue
        out.manual += m.val
    return out


POSTES = ("stake", "hold", "auto", "manuel", "autres")


def postes(
    liquid: Decimal,
    hold: Decimal,
    stake: Decimal,
    manual: Decimal,
    by_wallet_cat: dict,
    kinds: dict[str, str],
) -> dict[str, Decimal]:
    """Ventilation par poste (graphique « patrimoine par poste ») : staking (y compris manuel
    hors wallet), hold, liquidités du trading automatique, du trading manuel, autres liquidités.
    ``kinds`` : {id du wallet (texte) : poste}."""
    p = {"stake": stake + manual, "hold": hold, "auto": ZERO, "manuel": ZERO, "autres": ZERO}
    for wid, cats in (by_wallet_cat or {}).items():
        p[kinds.get(str(wid), "autres")] += Decimal(cats.get("liquid", ZERO))
    attributed = p["auto"] + p["manuel"] + p["autres"]
    if not by_wallet_cat and liquid:
        p["autres"] = liquid
    elif abs(attributed - liquid) > Decimal("0.01"):
        p["autres"] += liquid - attributed  # wallet supprimé depuis : le reste en « autres »
    return p
