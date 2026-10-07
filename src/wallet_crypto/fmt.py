"""Mise en forme à la française : « 1 234,56 $ », « 12,5 % »."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

NBSP = " "  # espace fine insécable, séparateur de milliers


def number(d: Decimal | None, places: int = 2, signed: bool = False) -> str:
    if d is None:
        return "—"
    if d.is_infinite():
        return "∞"
    q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) if places >= 0 else d
    sign = "-" if q < 0 else ("+" if signed and q > 0 else "")
    ent, _, dec = format(abs(q), "f").partition(".")
    groups = []
    while len(ent) > 3:
        groups.insert(0, ent[-3:])
        ent = ent[:-3]
    groups.insert(0, ent)
    out = NBSP.join(groups)
    return f"{sign}{out},{dec}" if dec else f"{sign}{out}"


def money(d: Decimal | None, currency: str = "USD", signed: bool = False, rate: Decimal | None = None) -> str:
    """Montant en dollars, ou en euros si ``currency`` = EUR et ``rate`` (€ pour 1 $) fourni."""
    if d is None:
        return "—"
    if currency == "EUR":
        if rate is None:
            return number(d, 2, signed) + " $"
        return number(d * rate, 2, signed) + " €"
    return number(d, 2, signed) + " $"


def qty(d: Decimal | None, price: Decimal | None = None) -> str:
    """Décimales adaptées au prix unitaire : 8 pour BTC, 4 au-delà de 1 $, 2 en dessous."""
    if d is None:
        return "—"
    if price and price >= 1000:
        return number(d, 8)
    if price and price >= 1:
        return number(d, 4)
    if price:
        return number(d, 2)
    if d == 0:
        return "0"
    places = min(8, max(0, -d.normalize().as_tuple().exponent))
    return number(d, places).rstrip("0").rstrip(",") if places else number(d, 0)


def pct(d: Decimal | None, places: int = 2, signed: bool = True) -> str:
    return "—" if d is None else f"{number(d, places, signed)} %"
