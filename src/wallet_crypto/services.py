"""Vues et actions de l'application : tout ce que l'interface affiche ou modifie passe ici.

Aucune dépendance à NiceGUI : ces fonctions se testent comme le moteur. Elles lisent la base,
appellent le moteur pur (``core``) et renvoient des structures prêtes à afficher. Les montants
restent des ``Decimal`` ; la conversion en ``float`` n'a lieu que pour les graphiques.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from .config import Config
from .core.assets import AssetLine, asset_base, asset_category, line_value
from .core.gains import gains_timeline
from .core.hold import HoldTx, build_hold_inputs, hold_position
from .core.manual_trades import ManualTrade, ManualTradeTx, trade_position
from .core.portfolio import auto_stake_bases, portfolio_summary, postes, wallet_kind
from .core.staking import (
    ManualStake,
    StakeRate,
    StakeTx,
    next_reward_date,
    stake_auto_metrics,
    stake_metrics,
)
from .core.trades import build_hl_trades, trade_stats
from .db import Database, store
from .db.models import (
    HlPosition,
    HoldTxRow,
    ManualStakeRateRow,
    ManualStakeRow,
    ManualStakeTxRow,
    ManualTradeRow,
    ManualTradeTxRow,
    StakeEventRow,
    Wallet,
)
from .money import ZERO, D

PriceFn = Callable[[str], Decimal | None]
DAY_MS = 86_400_000
POSTE_LABELS = {
    "stake": "Staking",
    "hold": "Hold",
    "auto": "Trading automatique",
    "manuel": "Trading manuel",
    "autres": "Autres liquidités",
}
CATEGORY_LABELS = {"liquid": "Liquidités", "hold": "Hold", "stake": "Staking"}


def _cached(s):
    return lambda base: store.cached_price(s, base)


def _kinds(wallets: list[Wallet]) -> dict[str, str]:
    return {str(w.id): wallet_kind(w.network, w.auto_trading) for w in wallets}


# ====================================================================== tableau de bord
@dataclass
class Delta:
    label: str
    amount: Decimal
    pct: Decimal | None
    since_ms: int


@dataclass
class DashboardView:
    total: Decimal
    liquid: Decimal
    hold: Decimal
    stake: Decimal
    manual: Decimal
    postes: dict[str, Decimal]
    deltas: list[Delta]
    unpriced: list[str]
    duplicates: list[str]
    n_wallets: int
    n_errors: int
    last_sync_ms: int | None
    eur_per_usd: Decimal | None
    has_wallets: bool
    top_assets: list[dict] = field(default_factory=list)


def dashboard(
    db: Database, config: Config, price_fn: PriceFn | None = None, now: int | None = None
) -> DashboardView:
    now = now or store.now_ms()
    with db.session() as s:
        wallets = store.load_wallet_assets(s)
        rows = store.list_wallets(s, active_only=True)
        cached = _cached(s)
        manual = store.manual_stake_items(s, price_fn or cached, auto_stake_bases(wallets), now, config.tz)
        summ = portfolio_summary(wallets, price_fn, cached, manual)
        snaps = {
            "depuis le début": (store.snapshots(s)[:1] or [None])[0],
            "7 jours": store.snapshot_before(s, now - 7 * DAY_MS),
            "24 h": store.snapshot_before(s, now - DAY_MS),
        }
        last = store.last_sync(s)
        eur = store.kv_get(s, "eur_per_usd")
        n_err = sum(1 for w in rows if w.last_error)
        kinds = _kinds(rows)
    deltas = []
    for label, snap in snaps.items():
        if snap and snap.total:
            amt = summ.total - snap.total
            deltas.append(Delta(label, amt, amt / snap.total * 100, snap.ts_ms))
    p = postes(
        summ.liquid,
        summ.hold,
        summ.stake,
        summ.manual,
        {str(k): v for k, v in summ.by_wallet_cat.items()},
        kinds,
    )
    top = sorted(
        ({"coin": k, **v} for k, v in summ.by_coin.items() if v["val"] > 0),
        key=lambda x: x["val"],
        reverse=True,
    )
    return DashboardView(
        total=summ.total,
        liquid=summ.liquid,
        hold=summ.hold,
        stake=summ.stake,
        manual=summ.manual,
        postes=p,
        deltas=deltas,
        unpriced=summ.unpriced,
        duplicates=summ.duplicates,
        n_wallets=summ.n_wallets,
        n_errors=n_err,
        last_sync_ms=last.started_ms if last else None,
        eur_per_usd=D(eur) if eur else None,
        has_wallets=bool(wallets),
        top_assets=top[:12],
    )


# ====================================================================== wallets
@dataclass
class LineView:
    coin: str
    qty: Decimal
    price: Decimal
    value: Decimal
    unpriced: bool
    category: str
    src: str
    extra: dict


@dataclass
class WalletView:
    id: int
    group: str
    label: str
    network: str
    address: str
    track_staking: bool
    auto_trading: bool
    is_active: bool
    last_sync_ms: int | None
    last_error: str | None
    total: Decimal
    lines: list[LineView]
    positions: list[dict]
    usdc_extra: dict | None


def wallets_view(db: Database, price_fn: PriceFn | None = None) -> dict[str, list[WalletView]]:
    groups: dict[str, list[WalletView]] = {}
    with db.session() as s:
        cached = _cached(s)
        for w in store.list_wallets(s):
            lines = []
            for coin, line in store.wallet_lines(s, w.id).items():
                v = line_value(line, price_fn, cached)
                if v.qty <= 0:
                    continue
                lines.append(
                    LineView(
                        coin, v.qty, v.price, v.value, v.unpriced, asset_category(coin), line.src, line.extra
                    )
                )
            lines.sort(key=lambda x: x.value, reverse=True)
            pos = [
                {
                    c: getattr(p, c)
                    for c in ("coin", "side", "size", "entry", "value", "upnl", "lev", "liq_px", "roe")
                }
                for p in s.scalars(select(HlPosition).where(HlPosition.wallet_id == w.id))
            ]
            usdc = next((ln.extra for ln in lines if ln.coin == "USDC" and w.network == "HL"), None)
            groups.setdefault(w.group_name, []).append(
                WalletView(
                    w.id, w.group_name, w.label, w.network, w.address, w.track_staking, w.auto_trading,
                    w.is_active, w.last_sync_ms, w.last_error, sum((ln.value for ln in lines), ZERO),
                    lines, pos, usdc,
                )
            )  # fmt: skip
    return groups


def update_wallet(db: Database, wallet_id: int, **fields: Any) -> None:
    allowed = {"label", "group_name", "track_staking", "auto_trading", "is_active"}
    with db.session() as s:
        w = s.get(Wallet, wallet_id)
        if w is None:
            return
        for k, v in fields.items():
            if k in allowed:
                setattr(w, k, v)
        if w.network != "HL":
            w.auto_trading = False


def delete_wallet(db: Database, wallet_id: int) -> None:
    with db.session() as s:
        w = s.get(Wallet, wallet_id)
        if w is not None:
            s.delete(w)


def add_wallets(
    db: Database, networks: list[str], addresses: list[str], group: str, label: str, track: bool, auto: bool
):
    """Ajout en masse : une adresse par ligne, plusieurs réseaux. Renvoie (ajoutés, erreurs)."""
    from .security import InputRejected

    added, errors = [], []
    clean = [a.strip() for a in addresses if a.strip()]
    for i, addr in enumerate(clean):
        lbl = label or "Principal"
        if len(clean) > 1:
            lbl = f"{label or 'Compte'} {i + 1}"
        for net in networks:
            try:
                with db.session() as s:
                    w = store.add_wallet(s, net, addr, lbl, group, track, auto)
                    added.append(f"{w.network} {w.address}")
            except InputRejected as exc:
                errors.append(f"{net} {addr[:12]}… : {exc}")
    return added, errors


# ====================================================================== staking
@dataclass
class AutoStakeView:
    source: str
    asset: str
    account: str
    address: str
    staked: Decimal
    pending: Decimal
    price: Decimal | None
    value: Decimal | None
    metrics: Any
    line_extra: dict
    events: list[dict]


@dataclass
class ManualStakeView:
    row: ManualStakeRow
    metrics: Any
    price: Decimal | None
    value: Decimal | None
    duplicate: bool
    rates: list[ManualStakeRateRow]
    txs: list[ManualStakeTxRow]
    next_reward_ms: int | None


@dataclass
class StakingView:
    autos: list[AutoStakeView]
    vaults: Decimal
    manuals: list[ManualStakeView]
    total_auto: Decimal
    total_manual: Decimal


def _price(
    base: str, price_fn: PriceFn | None, cached: PriceFn, line: AssetLine | None = None
) -> Decimal | None:
    return (price_fn(base) if price_fn else None) or (line.px_sync if line else None) or cached(base)


def staking_view(
    db: Database, config: Config, price_fn: PriceFn | None = None, now: int | None = None
) -> StakingView:
    now = now or store.now_ms()
    autos: list[AutoStakeView] = []
    vaults = ZERO
    with db.session() as s:
        cached = _cached(s)
        wallets = store.list_wallets(s, active_only=True)
        for w in wallets:
            lines = store.wallet_lines(s, w.id)
            name = f"{w.group_name} / {w.label}"
            specs = []
            if w.network == "HL" and "HYPE_STAKED" in lines:
                specs.append(("HL_HYPE", "HYPE", lines["HYPE_STAKED"], None, True))
            if w.network == "EVM" and ("WCT_STAKED" in lines or "WCT_PENDING" in lines):
                specs.append(("WCT_OP", "WCT", lines.get("WCT_STAKED"), lines.get("WCT_PENDING"), False))
            if "HLP_VAULTS" in lines:
                vaults += lines["HLP_VAULTS"].val or lines["HLP_VAULTS"].qty
            for source, asset, line, pend, compounding in specs:
                evs_rows = list(
                    s.scalars(
                        select(StakeEventRow)
                        .where(StakeEventRow.source == source, StakeEventRow.address == w.address)
                        .order_by(StakeEventRow.time_ms)
                    )
                )
                from .core.staking import StakeEvent

                evs = [StakeEvent(e.time_ms, e.kind, e.qty, e.hash) for e in evs_rows]
                staked = line.qty if line else ZERO
                pending = pend.qty if pend else ZERO
                m = stake_auto_metrics(evs, staked if line else None, pending, compounding, now)
                px = _price(asset, price_fn, cached, line or pend)
                autos.append(
                    AutoStakeView(
                        source, asset, name, w.address, staked, pending, px,
                        (staked + pending) * px if px else None, m, dict(line.extra) if line else {},
                        [{"time_ms": e.time_ms, "kind": e.kind, "qty": e.qty, "detail": e.detail} for e in reversed(evs_rows)],
                    )
                )  # fmt: skip
        auto_bases = {a.asset for a in autos}
        manuals = []
        for pos in s.scalars(
            select(ManualStakeRow).order_by(ManualStakeRow.active.desc(), ManualStakeRow.start_ms.desc())
        ):
            rates = list(
                s.scalars(
                    select(ManualStakeRateRow)
                    .where(ManualStakeRateRow.position_id == pos.id)
                    .order_by(ManualStakeRateRow.start_ms)
                )
            )
            txs = list(
                s.scalars(
                    select(ManualStakeTxRow)
                    .where(ManualStakeTxRow.position_id == pos.id)
                    .order_by(ManualStakeTxRow.time_ms)
                )
            )
            mp = _manual_stake(pos)
            m = stake_metrics(
                mp,
                [StakeRate(r.start_ms, r.end_ms, r.apr_pct) for r in rates],
                [StakeTx(t.time_ms, t.kind, t.qty, t.effective_ms) for t in txs],
                None, now, config.tz,
            )  # fmt: skip
            px = _price(pos.crypto.upper(), price_fn, cached)
            if px:
                m = stake_metrics(
                    mp,
                    [StakeRate(r.start_ms, r.end_ms, r.apr_pct) for r in rates],
                    [StakeTx(t.time_ms, t.kind, t.qty, t.effective_ms) for t in txs],
                    px, now, config.tz,
                )  # fmt: skip
            nxt = None
            if pos.active:
                nxt = int(
                    next_reward_date(
                        pos.compound_days, pos.reward_dow, pos.reward_dom, datetime.fromtimestamp(now / 1000, config.tz)
                    ).timestamp() * 1000
                )  # fmt: skip
            manuals.append(
                ManualStakeView(
                    pos, m, px, m.held_qty * px if px else None,
                    pos.active and pos.crypto.upper() in auto_bases, rates, txs, nxt,
                )
            )  # fmt: skip
    total_auto = sum((a.value or ZERO for a in autos), ZERO) + vaults
    total_manual = sum((m.value or ZERO for m in manuals if m.row.active and not m.duplicate), ZERO)
    return StakingView(autos, vaults, manuals, total_auto, total_manual)


def _manual_stake(pos: ManualStakeRow) -> ManualStake:
    return ManualStake(
        pos.id, pos.crypto.upper(), pos.start_ms, pos.mode, pos.compound_days, pos.reward_dow,
        pos.reward_dom, pos.rewards_restake, pos.fee_pct or ZERO, pos.entry_price, pos.end_ms,
    )  # fmt: skip


def create_manual_stake(
    db: Database,
    crypto: str,
    start_ms: int,
    mode: str,
    compound_days: int,
    qty: Decimal,
    apr_pct: Decimal,
    reward_dow: int | None = None,
    reward_dom: int | None = None,
    rewards_restake: bool = False,
    fee_pct: Decimal = ZERO,
    platform_url: str | None = None,
    entry_price: Decimal | None = None,
    notes: str | None = None,
) -> int:
    if not crypto.strip():
        raise ValueError("Crypto obligatoire.")
    if mode not in ("apr", "rewards"):
        raise ValueError("Mode inconnu.")
    with db.session() as s:
        pos = ManualStakeRow(
            crypto=crypto.strip().upper(), start_ms=start_ms, mode=mode, compound_days=compound_days,
            reward_dow=reward_dow if compound_days == 7 else None,
            reward_dom=reward_dom if compound_days == 30 else None,
            rewards_restake=rewards_restake, fee_pct=fee_pct, platform_url=platform_url or None,
            entry_price=entry_price, notes=notes,
        )  # fmt: skip
        s.add(pos)
        s.flush()
        if mode == "apr":
            s.add(ManualStakeRateRow(position_id=pos.id, start_ms=start_ms, end_ms=None, apr_pct=apr_pct))
        if qty > 0:
            s.add(ManualStakeTxRow(position_id=pos.id, time_ms=start_ms, kind="STAKE", qty=qty))
        return pos.id


def add_manual_stake_tx(
    db: Database, position_id: int, kind: str, time_ms: int, qty: Decimal, notes: str | None = None
):
    if kind not in ("STAKE", "UNSTAKE", "REWARD"):
        raise ValueError("Type inconnu.")
    if qty <= 0:
        raise ValueError("La quantité doit être positive.")
    with db.session() as s:
        s.add(ManualStakeTxRow(position_id=position_id, kind=kind, time_ms=time_ms, qty=qty, notes=notes))


def add_manual_stake_rate(db: Database, position_id: int, start_ms: int, apr_pct: Decimal) -> None:
    """Nouveau taux à partir d'une date : le taux en cours se termine à cette date."""
    with db.session() as s:
        open_rates = s.scalars(
            select(ManualStakeRateRow).where(
                ManualStakeRateRow.position_id == position_id, ManualStakeRateRow.end_ms.is_(None)
            )
        )
        for r in open_rates:
            if start_ms > r.start_ms:
                r.end_ms = start_ms
        s.add(ManualStakeRateRow(position_id=position_id, start_ms=start_ms, end_ms=None, apr_pct=apr_pct))


def end_manual_stake(db: Database, position_id: int, end_ms: int | None) -> None:
    with db.session() as s:
        pos = s.get(ManualStakeRow, position_id)
        if pos:
            pos.end_ms = end_ms
            pos.active = end_ms is None


def delete_row(db: Database, model, row_id: int) -> None:
    with db.session() as s:
        obj = s.get(model, row_id)
        if obj is not None:
            s.delete(obj)


# ====================================================================== hold
@dataclass
class HoldCard:
    base: str
    position: Any
    price: Decimal | None
    where: list[str]
    staked: Decimal
    n_hl: int
    n_manual: int
    held: bool


@dataclass
class HoldView:
    cards: list[HoldCard]
    gone: list[HoldCard]
    total_value: Decimal
    total_latent: Decimal
    total_realized: Decimal
    skipped_pairs: list[str]
    manual_txs: list[HoldTxRow]


def _hold_inputs(s, include_staked: bool):
    wallets = [
        (f"{w.group_name}/{w.label}", w.network, store.wallet_lines(s, w.id))
        for w in store.list_wallets(s, active_only=True)
    ]
    manual_rows = list(s.scalars(select(HoldTxRow).order_by(HoldTxRow.time_ms)))
    manual = [(r.crypto, HoldTx(r.time_ms, r.side, r.qty, r.price, "manuel")) for r in manual_rows]
    hl_addrs = [w.address for w in store.list_wallets(s, active_only=True) if w.network == "HL"]
    fills = [f for a in hl_addrs for f in store.fill_dicts(s, a, spot=True)]
    pairs = store.kv_get(s, "hl_spot_pairs", {}) or {}
    events = store.stake_events(s)
    pending = {}
    for _, _, lines in wallets:
        for coin, line in lines.items():
            if coin.upper().endswith("_PENDING"):
                pending[asset_base(coin)] = pending.get(asset_base(coin), ZERO) + line.qty
    return build_hold_inputs(wallets, manual, fills, pairs, events, pending, include_staked), manual_rows


def hold_view(db: Database, price_fn: PriceFn | None = None, include_staked: bool = True) -> HoldView:
    with db.session() as s:
        cached = _cached(s)
        hi, manual_rows = _hold_inputs(s, include_staked)
    cards, gone = [], []
    tv = tl = tr = ZERO
    for base, real in hi.real.items():
        px = (price_fn(base) if price_fn else None) or hi.prices.get(base) or cached(base)
        pos = hold_position(real["qty"], hi.txs.get(base, []), px, hi.rewards_free.get(base, ZERO))
        n = hi.n_src.get(base, {"hl": 0, "man": 0})
        cards.append(HoldCard(base, pos, px, real["where"], real["staked"], n["hl"], n["man"], True))
        tv += pos.value or ZERO
        tl += pos.latent or ZERO
        tr += pos.realized
    for base in sorted(set(hi.txs) - set(hi.real)):
        pos = hold_position(ZERO, hi.txs[base], None)
        if not pos.history:
            continue
        n = hi.n_src.get(base, {"hl": 0, "man": 0})
        gone.append(HoldCard(base, pos, None, [], ZERO, n["hl"], n["man"], False))
        tr += pos.realized
    cards.sort(key=lambda c: c.position.value or ZERO, reverse=True)
    return HoldView(cards, gone, tv, tl, tr, hi.skipped_pairs, manual_rows)


def add_hold_tx(
    db: Database, crypto: str, side: str, time_ms: int, qty: Decimal, price: Decimal, notes: str | None = None
):
    if side not in ("BUY", "SELL", "FEE"):
        raise ValueError("Sens inconnu.")
    if not crypto.strip():
        raise ValueError("Crypto obligatoire.")
    if qty <= 0:
        raise ValueError("La quantité doit être positive.")
    if side != "FEE" and price <= 0:
        raise ValueError("Le prix doit être positif.")
    with db.session() as s:
        s.add(
            HoldTxRow(
                crypto=crypto.strip().upper(),
                side=side,
                time_ms=time_ms,
                qty=qty,
                price=price if side != "FEE" else ZERO,
                notes=notes,
            )
        )


# ====================================================================== trades
@dataclass
class TradesView:
    accounts: dict[str, str]  # adresse → libellé
    selected: list[str]
    stats: dict
    by_coin: dict[str, dict]
    live: dict[tuple[str, str], dict]
    n_trades: int


def hl_accounts(db: Database) -> dict[str, tuple[str, bool]]:
    with db.session() as s:
        return {
            w.address: (f"{w.group_name} / {w.label}", w.auto_trading)
            for w in store.list_wallets(s)
            if w.network == "HL"
        }


def trades_view(
    db: Database, selected: list[str] | None = None, period_days: int | None = None, now: int | None = None
) -> TradesView:
    now = now or store.now_ms()
    accts = hl_accounts(db)
    if selected is None:
        selected = list(accts)
    selected = [a for a in selected if a in accts]
    trades = []
    live: dict[tuple[str, str], dict] = {}
    with db.session() as s:
        for a in selected:
            for t in build_hl_trades(store.fill_dicts(s, a, spot=False), store.funding_dicts(s, a), now):
                t["account"] = a
                t["account_label"] = accts[a][0]
                trades.append(t)
            w = s.scalar(select(Wallet).where(Wallet.address == a, Wallet.network == "HL"))
            if w:
                for p in s.scalars(select(HlPosition).where(HlPosition.wallet_id == w.id)):
                    live[(a, p.coin)] = {"upnl": p.upnl, "roe": p.roe, "lev": p.lev, "liq_px": p.liq_px}
    if period_days:
        cutoff = now - period_days * DAY_MS
        trades = [t for t in trades if t["close_time"] is None or t["close_time"] >= cutoff]
    trades.sort(key=lambda x: x["close_time"] or x["last_time"], reverse=True)
    by_coin: dict[str, dict] = {}
    for t in trades:
        by_coin.setdefault(t["coin"], {"trades": []})["trades"].append(t)
    for d in by_coin.values():
        d["stats"] = trade_stats(d["trades"])
    order = sorted(by_coin, key=lambda c: -abs(by_coin[c]["stats"]["net"]))
    return TradesView(
        {a: lbl for a, (lbl, _) in accts.items()},
        selected,
        trade_stats(trades),
        {c: by_coin[c] for c in order},
        live,
        len(trades),
    )


@dataclass
class ManualTradeView:
    row: ManualTradeRow
    txs: list[ManualTradeTxRow]
    metrics: dict
    price: Decimal | None


def manual_trades_view(db: Database, price_fn: PriceFn | None = None) -> list[ManualTradeView]:
    out = []
    with db.session() as s:
        cached = _cached(s)
        for tr in s.scalars(select(ManualTradeRow).order_by(ManualTradeRow.open_ms.desc())):
            txs = list(
                s.scalars(
                    select(ManualTradeTxRow)
                    .where(ManualTradeTxRow.trade_id == tr.id)
                    .order_by(ManualTradeTxRow.time_ms)
                )
            )
            px = (price_fn(tr.crypto) if price_fn else None) or cached(tr.crypto)
            m = trade_position(
                ManualTrade(tr.id, tr.crypto, tr.direction, tr.leverage, tr.pnl_override),
                [ManualTradeTx(t.time_ms, t.kind, t.qty, t.price) for t in txs],
                px,
            )
            out.append(ManualTradeView(tr, txs, m, px))
    out.sort(key=lambda v: (v.metrics["closed"], -v.row.open_ms))
    return out


def create_manual_trade(
    db: Database,
    crypto: str,
    direction: str,
    leverage: Decimal,
    open_ms: int,
    qty: Decimal,
    price: Decimal,
    platform: str | None = None,
    notes: str | None = None,
) -> int:
    if not crypto.strip():
        raise ValueError("Crypto obligatoire.")
    if direction not in ("LONG", "SHORT"):
        raise ValueError("Sens inconnu.")
    if qty <= 0 or price <= 0:
        raise ValueError("Quantité et prix doivent être positifs.")
    if leverage < 1:
        raise ValueError("Le levier vaut au moins 1.")
    with db.session() as s:
        tr = ManualTradeRow(
            crypto=crypto.strip().upper(),
            direction=direction,
            leverage=leverage,
            open_ms=open_ms,
            platform=platform or None,
            notes=notes,
        )
        s.add(tr)
        s.flush()
        s.add(ManualTradeTxRow(trade_id=tr.id, time_ms=open_ms, kind="OPEN", qty=qty, price=price))
        return tr.id


def add_manual_trade_tx(
    db: Database, trade_id: int, kind: str, time_ms: int, qty: Decimal, price: Decimal
) -> None:
    if kind not in ("ADD", "REDUCE"):
        raise ValueError("Type inconnu.")
    if qty <= 0 or price <= 0:
        raise ValueError("Quantité et prix doivent être positifs.")
    with db.session() as s:
        if kind == "REDUCE":
            txs = list(s.scalars(select(ManualTradeTxRow).where(ManualTradeTxRow.trade_id == trade_id)))
            held = sum((t.qty for t in txs if t.kind in ("OPEN", "ADD")), ZERO) - sum(
                (t.qty for t in txs if t.kind == "REDUCE"), ZERO
            )
            if qty > held:
                raise ValueError(f"Quantité supérieure à la position ({held}).")
        s.add(ManualTradeTxRow(trade_id=trade_id, kind=kind, time_ms=time_ms, qty=qty, price=price))


def set_manual_trade_override(db: Database, trade_id: int, pnl: Decimal | None) -> None:
    with db.session() as s:
        tr = s.get(ManualTradeRow, trade_id)
        if tr:
            tr.pnl_override = pnl


# ====================================================================== graphiques
def patrimoine_series(
    db: Database, live: DashboardView | None = None, now: int | None = None
) -> list[tuple[int, dict[str, Decimal]]]:
    """Un point par snapshot (ventilé par poste), plus le point « maintenant »."""
    out = []
    with db.session() as s:
        kinds = _kinds(store.list_wallets(s))
        for sn in store.snapshots(s):
            det = sn.detail or {}
            out.append(
                (
                    sn.ts_ms,
                    postes(sn.liquid, sn.hold, sn.stake, sn.manual, det.get("by_wallet_cat") or {}, kinds),
                )
            )
    if live is not None and live.has_wallets:
        out.append((now or store.now_ms(), live.postes))
    return out


def gain_start_options(db: Database, config: Config, now: int | None = None) -> dict[str, tuple[str, int]]:
    now = now or store.now_ms()
    opts: dict[str, tuple[str, int]] = {}
    with db.session() as s:
        firsts = [
            s.scalar(select(HoldTxRow.time_ms).order_by(HoldTxRow.time_ms).limit(1)),
            s.scalar(select(ManualStakeRow.start_ms).order_by(ManualStakeRow.start_ms).limit(1)),
            s.scalar(select(ManualTradeRow.open_ms).order_by(ManualTradeRow.open_ms).limit(1)),
        ]
        snaps = store.snapshots(s)
        from .db.models import HlFill

        evs = [
            s.scalar(select(HlFill.time_ms).order_by(HlFill.time_ms).limit(1)),
            s.scalar(select(StakeEventRow.time_ms).order_by(StakeEventRow.time_ms).limit(1)),
        ]

    def fmt(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, config.tz).strftime("%d/%m/%Y")

    firsts = [f for f in firsts if f]
    if firsts:
        opts["saisie"] = (f"Première saisie ({fmt(min(firsts))})", min(firsts))
    if snaps:
        opts["snapshot"] = (f"Premier relevé ({fmt(snaps[0].ts_ms)})", snaps[0].ts_ms)
    evs = [e for e in evs if e]
    if evs:
        opts["import"] = (f"Premier événement importé ({fmt(min(evs))})", min(evs))
    for n in (30, 90, 365):
        opts[f"{n}j"] = (
            f"{n} derniers jours",
            int((datetime.fromtimestamp(now / 1000, config.tz) - timedelta(days=n)).timestamp() * 1000),
        )
    return opts


def default_gain_start(opts: dict) -> str | None:
    for k in ("saisie", "snapshot", "import", "30j"):
        if k in opts:
            return k
    return None


def gains_data(db: Database, config: Config, start_ms: int, hist_price_fn, now: int | None = None) -> dict:
    """Gains cumulés par poste depuis ``start_ms``. ``hist_price_fn(base, t)`` : prix à un instant."""
    now = now or store.now_ms()
    with db.session() as s:
        wallets = store.list_wallets(s, active_only=True)
        kinds = {w.address: ("auto" if w.auto_trading else "manuel") for w in wallets if w.network == "HL"}
        fills = [f for a in kinds for f in store.fill_dicts(s, a, spot=False) if f["time_ms"] > start_ms]
        funding = [f for a in kinds for f in store.funding_dicts(s, a) if f["time_ms"] > start_ms]
        rewards = [
            (r.asset, r.time_ms, r.qty)
            for r in s.scalars(
                select(StakeEventRow).where(StakeEventRow.kind == "REWARD", StakeEventRow.time_ms > start_ms)
            )
        ]
        for pos in s.scalars(select(ManualStakeRow)):
            for tx in s.scalars(
                select(ManualStakeTxRow).where(
                    ManualStakeTxRow.position_id == pos.id, ManualStakeTxRow.kind == "REWARD"
                )
            ):
                rewards.append((pos.crypto.upper(), tx.time_ms, tx.qty))
        pending = []
        for w in wallets:
            for coin, line in store.wallet_lines(s, w.id).items():
                if coin.upper().endswith("_PENDING"):
                    pending.append((asset_base(coin), line.qty))
        hi, _ = _hold_inputs(s, include_staked=True)
    return gains_timeline(
        start_ms, now, fills, funding, kinds, rewards, pending, hi.txs, hist_price_fn, config.tz
    )


def hist_bases(db: Database) -> set[str]:
    """Actifs dont l'historique de prix sert au graphique des gains."""
    with db.session() as s:
        hi, _ = _hold_inputs(s, include_staked=True)
        bases = set(hi.txs) | {r for r in s.scalars(select(StakeEventRow.asset).distinct())}
        bases |= {p.crypto.upper() for p in s.scalars(select(ManualStakeRow))}
    return bases
