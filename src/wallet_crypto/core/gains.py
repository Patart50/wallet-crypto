"""Gains cumulés par poste depuis une date de départ (graphique « gains »).

- Trading automatique / manuel : Σ (PnL de prix − frais) des fills perp + funding, par compte.
  C'est du réalisé : le latent des positions ouvertes n'y est pas.
- Staking : récompenses reçues, valorisées au cours du moment de leur réception ;
  le réclamable est ajouté au dernier point.
- Hold : (réalisé + latent) de l'inventaire acheté, valorisé à chaque point, moins sa valeur
  au départ. Un actif sans historique de prix est exclu (et listé).

Gains ≠ variation du patrimoine : dépôts, retraits et achats ne sont pas des gains.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal

from ..money import EPS, ZERO
from .hold import HoldTx
from .trades import fill_fee, is_spot_coin

HistPriceFn = Callable[[str, int], Decimal | None]
MAX_POINTS = 400
GAIN_POSTES = ("stake", "hold", "auto", "manuel")


def day_grid(start_ms: int, now_ms: int, tz: tzinfo = UTC, max_points: int = MAX_POINTS) -> list[int]:
    """Fin de chaque jour (fuseau ``tz``) à partir du départ, puis maintenant. Au-delà de
    ``max_points`` jours, un jour sur N."""
    d = datetime.fromtimestamp(start_ms / 1000, tz).replace(hour=23, minute=59, second=59, microsecond=0)
    pts: list[int] = []
    while int(d.timestamp() * 1000) < now_ms:
        pts.append(int(d.timestamp() * 1000))
        d += timedelta(days=1)
    step = max(1, -(-len(pts) // max_points))
    pts = pts[::-1][::step][::-1]
    return [*pts, now_ms]


def cum_series(events: list[tuple[int, Decimal]], grid: list[int], start_ms: int) -> list[Decimal]:
    """Cumul des montants des événements tels que départ < t ≤ point de la grille."""
    ev = sorted(e for e in events if e[0] > start_ms)
    out, acc, i = [], ZERO, 0
    for g in grid:
        while i < len(ev) and ev[i][0] <= g:
            acc += ev[i][1]
            i += 1
        out.append(acc)
    return out


def inventory_at(txs: list[HoldTx], t: int) -> tuple[Decimal, Decimal, Decimal]:
    """(quantité, coût, réalisé) après les achats, ventes et frais jusqu'à ``t`` inclus.
    ``txs`` triés par date."""
    qty = cost = realized = ZERO
    for x in txs:
        if x.time_ms > t:
            break
        q = x.qty
        if q <= 0 or x.kind not in ("BUY", "SELL", "FEE"):
            continue
        if x.kind == "BUY":
            qty += q
            cost += q * (x.price or ZERO)
        elif x.kind == "FEE":
            qty -= min(q, qty)
            if qty <= EPS and cost:
                realized -= cost
                cost = ZERO
                qty = ZERO
        elif qty > 0:
            s = min(q, qty)
            pmp = cost / qty
            realized += s * ((x.price or ZERO) - pmp)
            cost -= s * pmp
            qty -= s
    return qty, cost, realized


def hold_gain_series(
    txs_by_asset: dict[str, list[HoldTx]], grid: list[int], start_ms: int, price_fn: HistPriceFn
) -> tuple[list[Decimal], list[str]]:
    vals = [ZERO] * len(grid)
    excluded: list[str] = []
    for base, all_txs in txs_by_asset.items():
        txs = sorted((x for x in all_txs if x.kind in ("BUY", "SELL", "FEE")), key=lambda x: x.time_ms)
        if not txs:
            continue

        def pnl(t: int, px: Decimal, txs: list[HoldTx] = txs) -> Decimal:
            q, c, r = inventory_at(txs, t)
            return r + (q * px - c if q > EPS else ZERO)

        p0 = price_fn(base, start_ms)
        if p0 is None and inventory_at(txs, start_ms)[0] > EPS:
            excluded.append(base)
            continue
        base0 = pnl(start_ms, p0 or ZERO)
        last_px = p0
        series: list[Decimal] = []
        ok = True
        for g in grid:
            px = price_fn(base, g) or last_px
            if px is None and inventory_at(txs, g)[0] > EPS:
                ok = False
                break
            last_px = px
            series.append(pnl(g, px or ZERO) - base0)
        if not ok:
            excluded.append(base)
            continue
        vals = [a + b for a, b in zip(vals, series, strict=True)]
    return vals, excluded


def gains_timeline(
    start_ms: int,
    now_ms: int,
    fills: list[dict],
    fundings: list[dict],
    account_kinds: dict[str, str],
    stake_rewards: list[tuple[str, int, Decimal]],
    pending: list[tuple[str, Decimal]],
    hold_txs: dict[str, list[HoldTx]],
    price_fn: HistPriceFn,
    tz: tzinfo = UTC,
) -> dict:
    """``fills`` / ``fundings`` portent ``address`` ; ``account_kinds`` : {adresse : auto|manuel} ;
    ``stake_rewards`` : [(actif, t, quantité)] (automatiques et saisies) ; ``pending`` :
    [(actif, quantité réclamable)]."""
    grid = day_grid(start_ms, now_ms, tz)
    ev: dict[str, list[tuple[int, Decimal]]] = {"auto": [], "manuel": []}
    for f in fills:
        if f["time_ms"] <= start_ms or is_spot_coin(f.get("coin")):
            continue
        k = account_kinds.get(f.get("address", ""), "manuel")
        ev[k].append((int(f["time_ms"]), (f.get("closed_pnl") or ZERO) - fill_fee(f)))
    for x in fundings:
        if x["time_ms"] <= start_ms:
            continue
        ev[account_kinds.get(x.get("address", ""), "manuel")].append(
            (int(x["time_ms"]), x.get("usdc") or ZERO)
        )
    st: list[tuple[int, Decimal]] = []
    unpriced_rewards = 0
    for asset, t, qty in stake_rewards:
        if t <= start_ms:
            continue
        px = price_fn(asset, t)
        if px:
            st.append((t, qty * px))
        else:
            unpriced_rewards += 1
    for asset, qty in pending:
        px = price_fn(asset, now_ms)
        if px:
            st.append((now_ms, qty * px))
    series = {
        "auto": cum_series(ev["auto"], grid, start_ms),
        "manuel": cum_series(ev["manuel"], grid, start_ms),
        "stake": cum_series(st, grid, start_ms),
    }
    series["hold"], excluded = hold_gain_series(hold_txs, grid, start_ms, price_fn)
    series["total"] = [sum((series[k][i] for k in GAIN_POSTES), ZERO) for i in range(len(grid))]
    return {
        "grid": grid,
        "series": series,
        "excluded": excluded,
        "unpriced_rewards": unpriced_rewards,
        "start": start_ms,
    }
