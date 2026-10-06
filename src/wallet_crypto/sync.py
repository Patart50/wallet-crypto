"""Synchronisation : lit chaque wallet, stocke soldes et historiques, photographie le patrimoine.

Règles (wallet D-007) :
- verrou de fichier : jamais deux synchronisations simultanées ;
- un wallet dont la source échoue garde ses anciens soldes (l'erreur est notée sur le wallet) ;
- l'échec d'un historique n'annule pas les soldes du même wallet ;
- un snapshot du patrimoine par synchronisation, si au moins un wallet a été lu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from .config import Config
from .core.assets import asset_base
from .core.portfolio import auto_stake_bases, portfolio_summary
from .db import Database, store
from .db.models import SyncRun, Wallet
from .lock import FileLock, LockBusy
from .prices import MarketPrices
from .sources import get_source
from .sources.http import Http

log = logging.getLogger("wallet_crypto.sync")


@dataclass
class SyncReport:
    status: str  # ok, busy, not_due, empty
    n_ok: int = 0
    n_errors: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    new_fills: int = 0
    new_funding: int = 0
    new_events: int = 0
    total: Decimal | None = None
    unpriced: list[str] = field(default_factory=list)
    duration_s: float = 0.0


def is_due(db: Database, config: Config, now: int) -> bool:
    with db.session() as s:
        last = store.last_sync(s, ok_only=True)
    return last is None or now - (last.finished_ms or 0) >= config.sync_hours * 3600_000


def _sync_wallet(
    db: Database, config: Config, http, market: MarketPrices, wallet_id: int, report: SyncReport, now: int
):
    with db.session() as s:
        w = s.get(Wallet, wallet_id)
        name = f"{w.group_name} / {w.label} ({w.network})"
        network, address, track = w.network, w.address, w.track_staking
    try:
        source = get_source(network, http, config.alchemy_key)
        res = source.fetch_balances(address, track)
    except Exception as exc:
        msg = str(exc)
        report.n_errors += 1
        report.errors.append((name, msg))
        log.error("ÉCHEC %s : %s (anciens soldes conservés)", name, msg)
        with db.session() as s:
            s.get(Wallet, wallet_id).last_error = msg[:500]
        return
    for coin, line in res.lines.items():  # prix Alchemy appris pour les lignes du même token
        if line.val is not None and line.src == "alchemy" and line.qty > 0:
            market.learn(asset_base(coin), line.val / line.qty)
    for coin, line in res.lines.items():
        if line.val is None:
            px = market.usd(asset_base(coin))
            if px:
                line.px_sync = px
    warnings = list(res.warnings)
    with db.session() as s:
        store.replace_lines(s, wallet_id, res.lines, res.keep_previous, now)
        if res.positions is not None:
            store.replace_positions(s, wallet_id, res.positions)
    try:
        with db.session() as s:
            cursor = store.history_cursor(s, address)
        batch = source.fetch_history(address, track, cursor)
        with db.session() as s:
            report.new_fills += store.store_fills(s, batch.fills)
            report.new_funding += store.store_funding(s, batch.funding)
            report.new_events += store.store_stake_events(s, batch.stake_events)
        warnings += batch.warnings
    except Exception as exc:
        warnings.append(f"Historique non importé : {exc}")
        log.error("Historique %s : %s", name, exc)
    with db.session() as s:
        w = s.get(Wallet, wallet_id)
        w.last_sync_ms = now
        w.last_error = None
    for wmsg in warnings:
        report.warnings.append((name, wmsg))
        log.warning("%s : %s", name, wmsg)
    report.n_ok += 1
    log.info("OK %s : %d actif(s)", name, len(res.lines))


def snapshot(db: Database, config: Config, market: MarketPrices, n_errors: int, now: int):
    with db.session() as s:
        wallets = store.load_wallet_assets(s)

        def fallback(base: str):
            return store.cached_price(s, base)

        manual = store.manual_stake_items(s, market.usd, auto_stake_bases(wallets), now, config.tz)
        summary = portfolio_summary(wallets, market.usd, fallback, manual)
        store.save_snapshot(s, summary, n_errors, now)
        for base, route in market.routes.items():
            px = market.usd(base)
            if px:
                store.set_cached_price(s, base, px, route)
        eur = market.eur_per_usd()
        if eur:
            store.kv_set(s, "eur_per_usd", eur)
    return summary


def run_sync(
    db: Database, config: Config, http=None, if_due: bool = False, now: int | None = None
) -> SyncReport:
    import time as _time

    t0 = _time.monotonic()
    now = now or store.now_ms()
    http = http or Http(config.secrets)
    lock = FileLock(config.lock_path)
    try:
        lock.acquire()
    except LockBusy:
        log.info("Synchronisation déjà en cours : ignorée")
        return SyncReport("busy")
    try:
        if if_due and not is_due(db, config, now):
            return SyncReport("not_due")
        with db.session() as s:
            run = SyncRun(started_ms=now)
            s.add(run)
            s.flush()
            run_id = run.id
            ids = [w.id for w in store.list_wallets(s, active_only=True)]
        if not ids:
            with db.session() as s:
                r = s.get(SyncRun, run_id)
                r.finished_ms, r.status, r.message = store.now_ms(), "empty", "aucun wallet"
            return SyncReport("empty")
        report = SyncReport("ok")
        market = MarketPrices.load(http)
        if market.hl_pairs:
            with db.session() as s:
                store.kv_set(s, "hl_spot_pairs", market.hl_pairs)
        for wid in ids:
            _sync_wallet(db, config, http, market, wid, report, now)
        if report.n_ok:
            try:
                summary = snapshot(db, config, market, report.n_errors, now)
                report.total = summary.total
                report.unpriced = summary.unpriced
            except Exception as exc:
                log.exception("Snapshot : %s", exc)
                report.warnings.append(("snapshot", str(exc)))
        report.duration_s = round(_time.monotonic() - t0, 1)
        with db.session() as s:
            r = s.get(SyncRun, run_id)
            r.finished_ms = store.now_ms()
            r.status = "ok" if report.n_ok else "error"
            r.n_ok, r.n_errors = report.n_ok, report.n_errors
            r.message = "; ".join(f"{n} : {m}" for n, m in report.errors)[:2000] or None
        log.info(
            "Synchronisation terminée : %d OK, %d erreur(s) en %.1f s",
            report.n_ok,
            report.n_errors,
            report.duration_s,
        )
        return report
    finally:
        lock.release()
