"""Montants en décimal exact (wallet D-008, D-013).

Tout montant, quantité ou prix est un ``Decimal``. Jamais de ``float`` dans les calculs :
un flottant binaire arrondit (0,1 + 0,2 = 0,30000000000000004). Les réponses d'API sont lues
en ``Decimal`` dès le parsing (``loads``). Le ``float`` n'apparaît qu'à l'affichage des
graphiques.

Précision : 50 chiffres significatifs, comme decimal.js dans les autres outils du programme.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal, DefaultContext, InvalidOperation, getcontext
from typing import Any

PRECISION = 50
DefaultContext.prec = PRECISION  # contextes des nouveaux threads (serveur, sync en tâche de fond)
getcontext().prec = PRECISION  # contexte du thread courant

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
EPS = Decimal("1e-12")  # en dessous : quantité considérée comme nulle


def D(x: Any) -> Decimal:
    """Convertit en ``Decimal``. ``None`` et chaîne vide donnent 0.

    Un ``float`` est converti par sa représentation la plus courte (``repr``) et non par son
    développement binaire : ``D(0.1) == Decimal("0.1")``.
    """
    if x is None:
        return ZERO
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise TypeError("un booléen n'est pas un montant")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))
    s = str(x).strip().replace(" ", "")
    if not s:
        return ZERO
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"montant illisible : {x!r}") from exc


def D_opt(x: Any) -> Decimal | None:
    """Comme ``D`` mais garde ``None`` (et la chaîne vide) comme absence de valeur."""
    if x is None or (isinstance(x, str) and not x.strip()):
        return None
    return D(x)


def loads(text: str | bytes) -> Any:
    """JSON avec les nombres à virgule lus en ``Decimal``."""
    return json.loads(text, parse_float=Decimal)


def to_str(d: Decimal | None) -> str | None:
    """Chaîne décimale sans exposant ni zéros inutiles (stockage, export)."""
    if d is None:
        return None
    if d == 0:
        return "0"
    s = format(d.normalize(), "f")
    return s


def json_default(o: Any) -> Any:
    """``default`` pour ``json.dumps`` : les ``Decimal`` deviennent des chaînes exactes."""
    if isinstance(o, Decimal):
        return to_str(o)
    raise TypeError(f"non sérialisable : {type(o).__name__}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=json_default, ensure_ascii=False, separators=(",", ":"))


def round_to(d: Decimal, places: int = 2) -> Decimal:
    """Arrondi au plus proche (demi vers le haut), pour l'affichage."""
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def is_zero(d: Decimal | None) -> bool:
    return d is None or abs(d) <= EPS


def safe_div(a: Decimal, b: Decimal) -> Decimal | None:
    """a ÷ b, ou ``None`` si b est nul."""
    if is_zero(b):
        return None
    return a / b
