"""Accès à la base : lecture et écriture des objets métier. Aucun appel réseau ici."""

from __future__ import annotations

import time
from datetime import tzinfo
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.assets import AssetLine, PriceFn
from ..core.portfolio import ManualStakeItem, PortfolioSummary, WalletAssets, wallet_kind
from ..core.staking import ManualStake, StakeEvent, StakeRate, StakeTx, stake_metrics
from ..money import D
from ..security import InputRejected, normalize_address
from .models import (
    KV,
    BalanceLine,
    HlFill,
    HlFunding,
    HlPosition,
    ManualStakeRateRow,
    ManualStakeRow,
    ManualStakeTxRow,
    PriceCache,
    Snapshot,
    StakeEventRow,
    SyncRun,
    Wallet,
)


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------- wallets
def add_wallet(
    s: Session,
    network: str,
    address: str,
    label: str = "",
    group_name: str = "Mon wallet",
    track_staking: bool = True,
    auto_trading: bool = False,
) -> Wallet:
    net = network.upper().strip()
    addr = normalize_address(net, address)
    exists = s.scalar(select(Wallet).where(Wallet.address == addr, Wallet.network == net))
    if exists:
        raise InputRejected(
            f"Cette adresse est déjà suivie sur {net} ({exists.group_name} / {exists.label})."
        )
    w = Wallet(
        network=net,
        address=addr,
        label=(label or "Principal").strip()[:60],
        group_name=(group_name or "Mon wallet").strip()[:60],
        track_staking=track_staking,
        auto_trading=auto_trading and net == "HL",
        created_ms=now_ms(),
    )
    s.add(w)
    s.flush()
    return w


def list_wallets(s: Session, active_only: bool = False) -> list[Wallet]:
    q = select(Wallet).order_by(Wallet.group_name, Wallet.label, Wallet.network)
    if active_only:
        q = q.where(Wallet.is_active.is_(True))
    return list(s.scalars(q))


def wallet_lines(s: Session, wallet_id: int) -> dict[str, AssetLine]:
    rows = s.scalars(select(BalanceLine).where(BalanceLine.wallet_id == wallet_id))
    return {r.coin: AssetLine(r.coin, r.qty, r.val, r.src, r.px_sync, dict(r.extra or {})) for r in rows}


def replace_lines(
    s: Session,
    wallet_id: int,
    lines: dict[str, AssetLine],
    keep_previous: tuple[str, ...] = (),
    ts: int | None = None,
) -> None:
    """Remplace les soldes d'un wallet après une lecture réussie. Les lignes de
    ``keep_previous`` (lecture partielle) reprennent leur valeur précédente si elles existaient."""
    ts = ts or now_ms()
    old = wallet_lines(s, wallet_id)
    for coin in keep_previous:
        if coin in old and coin not in lines:
            lines[coin] = old[coin]
    s.query(BalanceLine).filter(BalanceLine.wallet_id == wallet_id).delete()
    for coin, line in lines.items():
        s.add(
            BalanceLine(
                wallet_id=wallet_id,
                coin=coin,
                qty=line.qty,
                val=line.val,
                src=line.src,
                px_sync=line.px_sync,
                extra=line.extra or None,
                synced_ms=ts,
            )
        )


def replace_positions(s: Session, wallet_id: int, positions: list[dict]) -> None:
    s.query(HlPosition).filter(HlPosition.wallet_id == wallet_id).delete()
    for p in positions:
        s.add(
            HlPosition(
                wallet_id=wallet_id,
                **{
                    k: p[k]
                    for k in ("coin", "side", "size", "entry", "value", "upnl", "lev", "liq_px", "roe")
                },
            )
        )


def load_wallet_assets(s: Session) -> list[WalletAssets]:
    out = []
    for w in list_wallets(s, active_only=True):
        out.append(
            WalletAssets(
                w.id,
                f"{w.group_name} / {w.label}",
                w.network,
                wallet_lines(s, w.id),
                wallet_kind(w.network, w.auto_trading),
            )
        )
    return out


# ---------------------------------------------------------------- historiques
def history_cursor(s: Session, address: str):
    from ..sources.base import HistoryCursor

    last_fill = s.scalar(select(func.max(HlFill.time_ms)).where(HlFill.address == address))
    last_fund = s.scalar(select(func.max(HlFunding.time_ms)).where(HlFunding.address == address))
    sources = frozenset(
        s.scalars(select(StakeEventRow.source).where(StakeEventRow.address == address).distinct())
    )
    return HistoryCursor(last_fill, last_fund, sources)


def store_fills(s: Session, fills: list[dict]) -> int:
    n = 0
    by_addr: dict[str, set[int]] = {}
    for f in fills:
        known = by_addr.get(f["address"])
        if known is None:
            known = by_addr[f["address"]] = set(
                s.scalars(select(HlFill.tid).where(HlFill.address == f["address"]))
            )
        if f["tid"] in known:
            continue
        s.add(HlFill(**f))
        known.add(f["tid"])
        n += 1
    return n


def store_funding(s: Session, rows: list[dict]) -> int:
    n = 0
    known: dict[str, set[tuple[int, str]]] = {}
    for r in rows:
        k = known.get(r["address"])
        if k is None:
            k = known[r["address"]] = set(
                (t, c)
                for t, c in s.execute(
                    select(HlFunding.time_ms, HlFunding.coin).where(HlFunding.address == r["address"])
                )
            )
        key = (r["time_ms"], r["coin"])
        if key in k:
            continue
        s.add(HlFunding(**r))
        k.add(key)
        n += 1
    return n


def store_stake_events(s: Session, rows: list[dict]) -> int:
    if not rows:
        return 0
    ids = [r["ext_id"] for r in rows]
    known: set[str] = set()
    for i in range(0, len(ids), 500):
        known |= set(
            s.scalars(select(StakeEventRow.ext_id).where(StakeEventRow.ext_id.in_(ids[i : i + 500])))
        )
    n = 0
    for r in rows:
        if r["ext_id"] in known:
            continue
        s.add(StakeEventRow(**r))
        known.add(r["ext_id"])
        n += 1
    return n


def stake_events(
    s: Session, source: str | None = None, address: str | None = None
) -> dict[tuple[str, str], list[StakeEvent]]:
    """{(source, actif) : [événements]} — ou une seule position si ``address`` est donné."""
    q = select(StakeEventRow).order_by(StakeEventRow.time_ms)
    if source:
        q = q.where(StakeEventRow.source == source)
    if address:
        q = q.where(StakeEventRow.address == address)
    out: dict[tuple[str, str], list[StakeEvent]] = {}
    for r in s.scalars(q):
        out.setdefault((r.source, r.asset), []).append(StakeEvent(r.time_ms, r.kind, r.qty, r.hash))
    return out


def fill_dicts(s: Session, address: str | None = None, spot: bool | None = None) -> list[dict]:
    q = select(HlFill)
    if address:
        q = q.where(HlFill.address == address)
    if spot is not None:
        q = q.where(HlFill.is_spot.is_(spot))
    cols = [c.name for c in HlFill.__table__.columns if c.name != "id"]
    return [{c: getattr(f, c) for c in cols} for f in s.scalars(q)]


def funding_dicts(s: Session, address: str | None = None) -> list[dict]:
    q = select(HlFunding)
    if address:
        q = q.where(HlFunding.address == address)
    return [
        {"address": x.address, "time_ms": x.time_ms, "coin": x.coin, "usdc": x.usdc} for x in s.scalars(q)
    ]


# ---------------------------------------------------------------- staking manuel
def manual_stake_items(
    s: Session, price_fn: PriceFn, auto_bases: set[str], now: int | None = None, tz: tzinfo | None = None
) -> list[ManualStakeItem]:
    """Positions manuelles actives, valorisées ; doublon si l'actif est suivi en automatique."""
    items = []
    for pos in s.scalars(select(ManualStakeRow).where(ManualStakeRow.active.is_(True))):
        m = stake_metrics(
            ManualStake(
                pos.id, pos.crypto, pos.start_ms, pos.mode, pos.compound_days, pos.reward_dow,
                pos.reward_dom, pos.rewards_restake, pos.fee_pct or D(0), pos.entry_price, pos.end_ms,
            ),
            [StakeRate(r.start_ms, r.end_ms, r.apr_pct) for r in s.scalars(select(ManualStakeRateRow).where(ManualStakeRateRow.position_id == pos.id))],
            [StakeTx(t.time_ms, t.kind, t.qty, t.effective_ms) for t in s.scalars(select(ManualStakeTxRow).where(ManualStakeTxRow.position_id == pos.id))],
            now_ms=now,
            **({"tz": tz} if tz else {}),
        )  # fmt: skip
        pa = price_fn(pos.crypto.upper())
        qty = m.held_qty
        items.append(
            ManualStakeItem(
                pos.id, pos.crypto.upper(), qty, qty * pa if pa else None, pos.crypto.upper() in auto_bases
            )
        )
    return items


# ---------------------------------------------------------------- snapshot, prix, réglages
def save_snapshot(s: Session, summary: PortfolioSummary, n_errors: int, ts: int | None = None) -> Snapshot:
    snap = Snapshot(
        ts_ms=ts or now_ms(),
        total=summary.total,
        liquid=summary.liquid,
        hold=summary.hold,
        stake=summary.stake,
        manual=summary.manual,
        n_wallets=summary.n_wallets,
        n_errors=n_errors,
        n_unpriced=len(summary.unpriced),
        detail={
            "by_coin": {k: v["val"] for k, v in summary.by_coin.items()},
            "by_wallet": {str(k): v for k, v in summary.by_wallet.items()},
            "by_wallet_cat": {str(k): v for k, v in summary.by_wallet_cat.items()},
            "unpriced": summary.unpriced,
            "duplicates": summary.duplicates,
        },
    )
    s.add(snap)
    return snap


STAKE_SOURCE_NETWORK = {"HL_HYPE": "HL", "WCT_OP": "EVM"}


def purge_orphans(s: Session) -> dict[str, int]:
    """Retire ce qui appartient à des wallets qui ne sont plus suivis (wallet D-031) :

    - leur part dans les relevés du patrimoine (``by_wallet_cat`` de chaque relevé : liquidités,
      hold, staking soustraits du relevé) ;
    - leur historique importé : fills et funding Hyperliquid, mouvements de staking.

    Utile après une adresse ajoutée par erreur (un contrat, l'adresse de quelqu'un d'autre).
    Un wallet en pause reste suivi : rien n'est retiré pour lui. Renvoie les nombres retirés."""
    wallets = list(s.scalars(select(Wallet)))
    ids = {str(w.id) for w in wallets}
    tracked = {(w.address, w.network) for w in wallets}
    out = {"snapshots": 0, "fills": 0, "funding": 0, "stake_events": 0}

    for snap in s.scalars(select(Snapshot)):
        det = dict(snap.detail or {})
        cats = dict(det.get("by_wallet_cat") or {})
        orphans = [wid for wid in cats if wid not in ids]
        if not orphans:
            continue
        for wid in orphans:
            c = cats.pop(wid) or {}
            liquid, hold, stake = (D(c.get(k)) for k in ("liquid", "hold", "stake"))
            snap.liquid -= liquid
            snap.hold -= hold
            snap.stake -= stake
            snap.total -= liquid + hold + stake
            (det.get("by_wallet") or {}).pop(wid, None)
        det["by_wallet_cat"] = cats
        det.pop("by_coin", None)  # non ventilé par wallet : retiré plutôt que laissé faux
        det["purged_wallets"] = sorted(set(det.get("purged_wallets") or []) | set(orphans))
        snap.detail = det
        out["snapshots"] += 1

    hl_tracked = {a for a, n in tracked if n == "HL"}
    for model, key in ((HlFill, "fills"), (HlFunding, "funding")):
        for addr in set(s.scalars(select(model.address).distinct())) - hl_tracked:
            out[key] += s.query(model).filter(model.address == addr).delete()
    for source, addr in {
        (r[0], r[1]) for r in s.execute(select(StakeEventRow.source, StakeEventRow.address).distinct())
    }:
        if (addr, STAKE_SOURCE_NETWORK.get(source, "")) not in tracked:
            out["stake_events"] += (
                s.query(StakeEventRow)
                .filter(StakeEventRow.source == source, StakeEventRow.address == addr)
                .delete()
            )
    return out


def snapshots(s: Session) -> list[Snapshot]:
    return list(s.scalars(select(Snapshot).order_by(Snapshot.ts_ms)))


def snapshot_before(s: Session, ts: int) -> Snapshot | None:
    return s.scalar(select(Snapshot).where(Snapshot.ts_ms <= ts).order_by(Snapshot.ts_ms.desc()).limit(1))


def cached_price(s: Session, base: str) -> Decimal | None:
    row = s.get(PriceCache, base.upper())
    return row.price if row else None


def set_cached_price(s: Session, base: str, price: Decimal, source: str = "") -> None:
    row = s.get(PriceCache, base.upper())
    if row is None:
        s.add(PriceCache(base=base.upper(), price=price, source=source, updated_ms=now_ms()))
    else:
        row.price, row.source, row.updated_ms = price, source, now_ms()


def kv_get(s: Session, key: str, default: Any = None) -> Any:
    row = s.get(KV, key)
    return row.value if row else default


def kv_set(s: Session, key: str, value: Any) -> None:
    row = s.get(KV, key)
    if row is None:
        s.add(KV(key=key, value=value))
    else:
        row.value = value


def last_sync(s: Session, ok_only: bool = False) -> SyncRun | None:
    """Dernière synchronisation terminée (``ok_only`` : au moins un wallet lu)."""
    q = select(SyncRun).where(SyncRun.finished_ms.is_not(None))
    q = q.where(SyncRun.status == "ok") if ok_only else q.where(SyncRun.status != "empty")
    return s.scalar(q.order_by(SyncRun.started_ms.desc()).limit(1))
