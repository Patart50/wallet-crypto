"""Trades Hyperliquid reconstruits à partir des fills.

Un trade = la position d'un actif qui part de zéro et y revient. Renforts, réductions
partielles et retournements (fill « Long > Short » coupé en fermeture puis ouverture) sont
gérés. Net = PnL de prix (``closedPnl``, hors frais chez Hyperliquid) − frais (+ builder)
+ funding. Un trade déjà ouvert avant le premier fill disponible (Hyperliquid n'en sert que
10 000) est marqué « incomplet ».

Fills : dicts {tid, coin, side ('B' achat, 'A' vente), px, sz, start_position, closed_pnl, fee,
fee_token, builder_fee, time_ms, dir, liquidation}, montants en ``Decimal``.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

from ..money import HUNDRED, ONE, ZERO

FEE_STABLES = ("USDC", "USDT", "USDE", "USDH")
_CLOSE_TOL = Decimal("1e-7")


def is_spot_coin(coin: str | None) -> bool:
    """Fill spot : ``@107`` ou ``PURR/USDC`` ; un perp est nommé par son actif (``BTC``)."""
    c = str(coin or "")
    return c.startswith("@") or "/" in c


def fill_fee(f: dict) -> Decimal:
    """Frais d'un fill en USD. Les frais payés dans un autre token (rare en perp) sont ignorés."""
    tok = str(f.get("fee_token") or "USDC").upper()
    fee = (f.get("fee") or ZERO) if tok in FEE_STABLES else ZERO
    return fee + (f.get("builder_fee") or ZERO)


def _signed_sz(f: dict) -> Decimal:
    sz = f.get("sz") or ZERO
    return sz if f.get("side") == "B" else -sz


def _close_enough(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= _CLOSE_TOL * max(ONE, abs(a), abs(b))


def chain_order(group: list[dict]) -> list[dict]:
    """Fills d'un même instant (un ordre exécuté en plusieurs morceaux) : le ``tid`` ne suit
    pas l'ordre d'exécution. On les chaîne par quantité : chaque fill démarre là où le
    précédent finit (position de départ + taille signée)."""
    if len(group) <= 1:
        return list(group)
    items = list(group)
    ends = [(f.get("start_position") or ZERO) + _signed_sz(f) for f in items]
    head = 0
    for i, f in enumerate(items):
        st = f.get("start_position") or ZERO
        if not any(_close_enough(st, e) for j, e in enumerate(ends) if j != i):
            head = i
            break
    ordered = [items.pop(head)]
    while items:
        cur_end = (ordered[-1].get("start_position") or ZERO) + _signed_sz(ordered[-1])
        k = next(
            (j for j, f in enumerate(items) if _close_enough(f.get("start_position") or ZERO, cur_end)), None
        )
        if k is None:  # chaîne rompue : ordre par position de départ
            ordered += sorted(items, key=lambda f: f.get("start_position") or ZERO)
            break
        ordered.append(items.pop(k))
    return ordered


def _new_trade(coin: str, side: str, t: int, incomplete: bool = False, start_size: Decimal = ZERO) -> dict:
    return {
        "coin": coin,
        "side": side,
        "open_time": t,
        "close_time": None,
        "last_time": t,
        "opens": [],
        "closes": [],
        "closed_pnl": ZERO,
        "fees": ZERO,
        "funding": ZERO,
        "size_max": start_size,
        "qty_open": start_size,
        "n_fills": 0,
        "incomplete": incomplete,
        "liquidated": False,
        "gap": False,
    }


def _vwap(legs: list[tuple[Decimal, Decimal]]) -> Decimal | None:
    q = sum((x for _, x in legs), ZERO)
    return sum((p * x for p, x in legs), ZERO) / q if q > 0 else None


def build_hl_trades(
    fills: list[dict], fundings: list[dict] | None = None, now_ms: int | None = None
) -> list[dict]:
    """Perps uniquement (fills spot ignorés). ``fundings`` : dicts {time_ms, coin, usdc}
    (usdc négatif = payé). Renvoie les trades, du plus récent au plus ancien."""
    by_coin: dict[str, list[dict]] = {}
    for f in fills:
        if is_spot_coin(f.get("coin")):
            continue
        by_coin.setdefault(f["coin"], []).append(f)

    trades: list[dict] = []
    for coin, fl in by_coin.items():
        fl.sort(key=lambda f: (int(f["time_ms"]), int(f.get("tid") or 0)))
        ordered: list[dict] = []
        for _, grp in itertools.groupby(fl, key=lambda f: int(f["time_ms"])):
            ordered.extend(chain_order(list(grp)))
        cur = None
        for f in ordered:
            sz = f.get("sz") or ZERO
            if sz <= 0:
                continue
            t = int(f["time_ms"])
            signed = sz if f.get("side") == "B" else -sz
            start = f.get("start_position") or ZERO
            eps = Decimal("1e-9") * max(ONE, abs(start), sz)
            fee = fill_fee(f)
            liq = bool(f.get("liquidation")) or "liquidat" in str(f.get("dir") or "").lower()

            if abs(start) <= eps and cur is not None:
                cur["gap"] = True  # fills manquants : on clôt le trade en cours
                cur["close_time"] = cur["last_time"]
                trades.append(cur)
                cur = None
            if cur is None and abs(start) > eps:
                cur = _new_trade(
                    coin, "LONG" if start > 0 else "SHORT", t, incomplete=True, start_size=abs(start)
                )

            reducing = abs(start) > eps and (signed > 0) != (start > 0)
            close_qty = min(sz, abs(start)) if reducing else ZERO
            open_qty = sz - close_qty
            frac = close_qty / sz

            if close_qty > eps:
                cur["closes"].append((f["px"], close_qty))
                cur["closed_pnl"] += f.get("closed_pnl") or ZERO
                cur["fees"] += fee * frac
                cur["n_fills"] += 1
                cur["last_time"] = t
                cur["liquidated"] = cur["liquidated"] or liq
                cur["qty_open"] = abs(start) - close_qty
                if cur["qty_open"] <= eps:
                    cur["qty_open"] = ZERO
                    cur["close_time"] = t
                    trades.append(cur)
                    cur = None

            if open_qty > eps:
                if cur is None:
                    cur = _new_trade(coin, "LONG" if signed > 0 else "SHORT", t)
                cur["opens"].append((f["px"], open_qty))
                cur["fees"] += fee * (ONE - frac)
                if close_qty <= eps:
                    cur["n_fills"] += 1
                cur["last_time"] = t
                cur["qty_open"] = abs(start + signed) if close_qty <= eps else open_qty
                cur["size_max"] = max(cur["size_max"], cur["qty_open"])
        if cur is not None:
            trades.append(cur)

    fund_by_coin: dict[str, list[tuple[int, Decimal]]] = {}
    for fu in fundings or []:
        fund_by_coin.setdefault(fu["coin"], []).append((int(fu["time_ms"]), fu.get("usdc") or ZERO))
    horizon = now_ms or 10**15
    for tr in trades:
        end = tr["close_time"] if tr["close_time"] is not None else horizon
        tr["funding"] = sum(
            (u for tm, u in fund_by_coin.get(tr["coin"], []) if tr["open_time"] <= tm <= end), ZERO
        )
        tr["entry_px"] = _vwap(tr["opens"])
        tr["exit_px"] = _vwap(tr["closes"])
        tr["net"] = tr["closed_pnl"] - tr["fees"] + tr["funding"]
        base_px = tr["entry_px"] or tr["exit_px"] or ZERO
        tr["notional_max"] = tr["size_max"] * base_px
        tr["ret_pct"] = tr["net"] / tr["notional_max"] * HUNDRED if tr["notional_max"] else None
        end_t = tr["close_time"] if tr["close_time"] is not None else (now_ms or tr["last_time"])
        tr["duration_min"] = Decimal(end_t - tr["open_time"]) / 60_000
    trades.sort(key=lambda x: x["close_time"] or x["last_time"], reverse=True)
    return trades


def trade_stats(trades: list[dict]) -> dict:
    """Statistiques sur les trades **clos**, nettes de frais et de funding.

    Profit factor = Σ gains ÷ Σ pertes (``Infinity`` sans perte, ``None`` sans trade gagnant ni
    perdant). Le winrate n'est jamais montré seul : gain et perte moyens, espérance."""
    closed = [t for t in trades if t["close_time"] is not None]
    n = len(closed)
    wins = [t["net"] for t in closed if t["net"] > 0]
    losses = [t["net"] for t in closed if t["net"] < 0]
    gw, gl = sum(wins, ZERO), -sum(losses, ZERO)
    net = sum((t["net"] for t in closed), ZERO)
    if gl > 0:
        pf: Decimal | None = gw / gl
    else:
        pf = Decimal("Infinity") if gw > 0 else None
    return {
        "n": n,
        "n_open": len(trades) - n,
        "wr": Decimal(len(wins)) / n * HUNDRED if n else None,
        "pf": pf,
        "net": net,
        "avg_win": gw / len(wins) if wins else None,
        "avg_loss": -gl / len(losses) if losses else None,
        "expectancy": net / n if n else None,
        "fees": sum((t["fees"] for t in closed), ZERO),
        "funding": sum((t["funding"] for t in closed), ZERO),
        "best": max((t["net"] for t in closed), default=None),
        "worst": min((t["net"] for t in closed), default=None),
        "n_incomplete": sum(1 for t in closed if t["incomplete"]),
    }
