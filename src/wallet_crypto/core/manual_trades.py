"""Trades saisis à la main (autres plateformes), en attendant leurs connecteurs.

Le levier est porté par la position. La quantité saisie inclut déjà le levier :
marge = notionnel d'entrée ÷ levier ; PnL en USD = quantité × écart de prix (indépendant du
levier) ; ROE = PnL ÷ marge. Mouvements : OPEN, ADD (augmentent), REDUCE (réduit, tout ou
partie). Un PnL réalisé réel peut être saisi (frais et funding de la plateforme inclus) : il
remplace le PnL calculé.

Ne pas ressaisir ici les trades Hyperliquid : ils sont importés automatiquement.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..money import EPS, HUNDRED, ONE, ZERO


@dataclass
class ManualTrade:
    id: int
    crypto: str
    direction: str = "LONG"  # LONG / SHORT
    leverage: Decimal = ONE
    pnl_override: Decimal | None = None


@dataclass
class ManualTradeTx:
    time_ms: int
    kind: str  # OPEN, ADD, REDUCE
    qty: Decimal
    price: Decimal


def trade_position(trade: ManualTrade, txs: list[ManualTradeTx], price_now: Decimal | None = None) -> dict:
    sign = ONE if trade.direction.upper() == "LONG" else -ONE
    lev = trade.leverage or ONE
    qty = cost = realized = ZERO
    for t in sorted(txs, key=lambda x: x.time_ms):
        if t.kind in ("OPEN", "ADD"):
            cost += t.qty * t.price
            qty += t.qty
        elif t.kind == "REDUCE" and qty > 0:
            pmp = cost / qty
            red = min(t.qty, qty)
            realized += sign * red * (t.price - pmp)
            cost -= red * pmp
            qty -= red
    pmp = cost / qty if qty > EPS else ZERO
    notion_in = qty * pmp
    margin = notion_in / lev if lev else ZERO
    has_px = price_now is not None and qty > EPS
    latent = sign * qty * (price_now - pmp) if has_px else None
    roe = latent / margin * HUNDRED if latent is not None and margin else None
    return {
        "qty": qty,
        "pmp": pmp,
        "margin": margin,
        "notion_in": notion_in,
        "notion_now": qty * price_now if has_px else None,
        "latent": latent,
        "realized": trade.pnl_override if trade.pnl_override is not None else realized,
        "realized_calc": realized,
        "override": trade.pnl_override,
        "roe": roe,
        "closed": qty <= EPS,
    }
