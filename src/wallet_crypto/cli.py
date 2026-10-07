"""Ligne de commande ``wallet-crypto``.

wallet-crypto wallet add HL,EVM 0x… --label "Compte 1" --group "MetaMask"
wallet-crypto wallet list
wallet-crypto sync            (ou --if-due pour cron : seulement si la dernière date de plus de 6 h)
wallet-crypto status [--eur]  (patrimoine d'après la dernière synchronisation, sans réseau)
wallet-crypto trades          (statistiques des trades Hyperliquid archivés)
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from . import __version__, fmt
from .config import Config, load_config
from .core.portfolio import auto_stake_bases, portfolio_summary
from .core.trades import build_hl_trades, trade_stats
from .db import Database, store
from .db.models import HlPosition, Wallet
from .log import setup_logging
from .security import InputRejected, mask_secret
from .support import AUTHOR_DISPLAY, REPO_URL, SPONSORS_URL


def _db(config: Config) -> Database:
    config.ensure_dirs()
    db = Database(config.db_path)
    db.init()
    return db


def cmd_wallet_add(config: Config, args) -> int:
    db = _db(config)
    networks = [n.strip().upper() for n in args.network.split(",") if n.strip()]
    added = 0
    for net in networks:
        try:
            with db.session() as s:
                w = store.add_wallet(
                    s, net, args.address, args.label, args.group, not args.no_staking, args.auto_trading
                )
                print(f"Ajouté : #{w.id} {w.group_name} / {w.label} ({w.network}) {w.address}")
                added += 1
        except InputRejected as exc:
            print(f"{net} : {exc}", file=sys.stderr)
    if added and any(n in ("EVM", "SOL") for n in networks) and not config.alchemy_key:
        print("Attention : clé Alchemy absente, les wallets EVM et Solana ne seront pas lus. Voir le README.")
    return 0 if added else 1


def cmd_wallet_list(config: Config, args) -> int:
    db = _db(config)
    with db.session() as s:
        wallets = store.list_wallets(s)
        if not wallets:
            print("Aucun wallet. Ajoutez-en un : wallet-crypto wallet add HL 0x…")
            return 0
        for w in wallets:
            flags = []
            if not w.is_active:
                flags.append("désactivé")
            if w.auto_trading:
                flags.append("trading automatique")
            if not w.track_staking:
                flags.append("staking non suivi")
            state = "jamais synchronisé" if not w.last_sync_ms else "synchronisé"
            err = f"  ⚠ {w.last_error}" if w.last_error else ""
            print(
                f"#{w.id:<3} {w.network:<4} {w.group_name} / {w.label}  {w.address}  [{state}{', ' if flags else ''}{', '.join(flags)}]{err}"
            )
    return 0


def cmd_wallet_remove(config: Config, args) -> int:
    db = _db(config)
    with db.session() as s:
        w = s.get(Wallet, args.id)
        if w is None:
            print(f"Wallet #{args.id} introuvable.", file=sys.stderr)
            return 1
        s.delete(w)
        print(f"Supprimé : #{args.id} {w.group_name} / {w.label} ({w.network})")
    return 0


def cmd_sync(config: Config, args) -> int:
    from .sync import run_sync

    db = _db(config)
    rep = run_sync(db, config, if_due=args.if_due)
    if rep.status == "busy":
        print("Une synchronisation est déjà en cours.")
        return 0
    if rep.status == "not_due":
        print("Pas encore due (dernière synchronisation récente).")
        return 0
    if rep.status == "empty":
        print("Aucun wallet à synchroniser. Ajoutez-en un : wallet-crypto wallet add HL 0x…")
        return 0
    print(f"Synchronisation : {rep.n_ok} wallet(s) lu(s), {rep.n_errors} erreur(s) en {rep.duration_s} s.")
    print(
        f"Historique : +{rep.new_fills} fills, +{rep.new_funding} funding, +{rep.new_events} mouvements de staking."
    )
    for name, msg in rep.errors:
        print(f"  ✗ {name} : {msg}")
    for name, msg in rep.warnings:
        print(f"  ! {name} : {msg}")
    if rep.total is not None:
        print(f"Patrimoine : {fmt.money(rep.total)}")
    if rep.unpriced:
        print(f"Sans prix (non comptés) : {', '.join(rep.unpriced)}")
    return 0 if rep.n_ok or not rep.n_errors else 2


def cmd_status(config: Config, args) -> int:
    db = _db(config)
    with db.session() as s:
        wallets = store.load_wallet_assets(s)
        if not wallets:
            print("Aucun wallet. Ajoutez-en un : wallet-crypto wallet add HL 0x…")
            return 0
        rate = store.kv_get(s, "eur_per_usd") if args.eur else None
        cur = "EUR" if args.eur and rate else "USD"

        def cached(base):
            return store.cached_price(s, base)

        manual = store.manual_stake_items(s, cached, auto_stake_bases(wallets), tz=config.tz)
        summ = portfolio_summary(wallets, None, cached, manual)
        last = store.last_sync(s)
        first = store.snapshots(s)[:1]
        positions = list(s.scalars(select(HlPosition)))

    def m(x, signed=False):
        return fmt.money(x, cur, signed, rate)

    print(f"Patrimoine global : {m(summ.total)}")
    print(
        f"  Liquidités {m(summ.liquid)} · Hold {m(summ.hold)} · Staking {m(summ.stake)}"
        + (f" · Staking hors wallet {m(summ.manual)}" if summ.manual else "")
    )
    if first and first[0].total:
        delta = summ.total - first[0].total
        print(
            f"  Depuis le premier snapshot : {m(delta, True)} (évolution brute, dépôts et retraits compris)"
        )
    if summ.unpriced:
        print(f"  ⚠ Sans prix, non comptés : {', '.join(summ.unpriced)}")
    if summ.duplicates:
        print(f"  ⚠ Staking manuel exclu (déjà suivi automatiquement) : {', '.join(summ.duplicates)}")
    if positions:
        print("Positions Hyperliquid ouvertes :")
        for p in positions:
            print(
                f"  {p.coin} {p.side} {fmt.qty(p.size, p.entry)} @ {fmt.number(p.entry, 4)}  PnL latent {m(p.upnl, True)}"
            )
    if last:
        from datetime import datetime

        when = datetime.fromtimestamp(last.started_ms / 1000, config.tz).strftime("%d/%m/%Y %H:%M")
        print(f"Dernière synchronisation : {when} ({last.n_ok} OK, {last.n_errors} erreur(s))")
    else:
        print("Jamais synchronisé : lancez wallet-crypto sync")
    return 0


def cmd_trades(config: Config, args) -> int:
    db = _db(config)
    with db.session() as s:
        hl = [w for w in store.list_wallets(s) if w.network == "HL"]
        fills_by, fund_by = {}, {}
        for w in hl:
            fills_by[w.address] = store.fill_dicts(s, w.address, spot=False)
            fund_by[w.address] = store.funding_dicts(s, w.address)
    trades = []
    for addr in fills_by:  # une position est propre à un compte : reconstruction par compte
        trades += build_hl_trades(fills_by[addr], fund_by[addr], store.now_ms())
    if not trades:
        print("Aucun trade Hyperliquid archivé (lancez wallet-crypto sync).")
        return 0
    st = trade_stats(trades)
    print(f"Trades clos : {st['n']} · ouverts : {st['n_open']}")
    if st["n"]:
        print(
            f"  Net {fmt.money(st['net'], signed=True)} (frais {fmt.money(st['fees'])}, funding {fmt.money(st['funding'], signed=True)})"
        )
        print(
            f"  Winrate {fmt.pct(st['wr'], 1, False)} · profit factor {fmt.number(st['pf'])} · espérance {fmt.money(st['expectancy'], signed=True)} par trade"
        )
        print(
            f"  Gain moyen {fmt.money(st['avg_win'], signed=True)} · perte moyenne {fmt.money(st['avg_loss'], signed=True)}"
        )
        if st["n_incomplete"]:
            print(
                f"  ⚠ {st['n_incomplete']} trade(s) incomplet(s) : ouverts avant le début de l'historique Hyperliquid."
            )
    return 0


def cmd_serve(config: Config, args) -> int:
    import dataclasses

    try:
        from .ui.app import serve
    except ImportError as exc:  # pragma: no cover - installation incomplète
        print(f"Interface indisponible ({exc}). Réinstallez : pip install .", file=sys.stderr)
        return 1
    if args.demo:
        config = dataclasses.replace(config, data_dir=config.data_dir.parent / "data-demo", alchemy_key="")
        config.ensure_dirs()
        db = Database(config.db_path)
        db.init()
        with db.session() as s:
            empty = not store.list_wallets(s)
        if empty:
            from .demo import build_demo

            build_demo(db)
            print(f"Base de démonstration fictive créée dans {config.data_dir}")
    password = config.password or None
    if password and len(password) < 8:
        print("WALLET_CRYPTO_PASSWORD : 8 caractères minimum.", file=sys.stderr)
        return 1
    serve(config, host=args.host, port=args.port, demo=args.demo, docker=args.docker, env_password=password)
    return 0


def cmd_about(config: Config, args) -> int:
    print(f"wallet-crypto {__version__} — créé par {AUTHOR_DISPLAY}")
    print(f"Code source (AGPL-3.0) : {REPO_URL}")
    print(f"Soutenir le projet : {SPONSORS_URL}")
    print(f"Données : {config.data_dir}")
    print(f"Clé Alchemy : {mask_secret(config.alchemy_key) or 'absente'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wallet-crypto", description="Suivi de patrimoine crypto auto-hébergé, en lecture seule."
    )
    p.add_argument("--version", action="version", version=f"wallet-crypto {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="journal détaillé dans la console")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("wallet", help="gérer les adresses suivies").add_subparsers(dest="wcmd", required=True)
    a = w.add_parser("add", help="suivre une adresse publique")
    a.add_argument("network", help="HL, EVM, SOL ou BTC ; plusieurs séparés par des virgules (HL,EVM)")
    a.add_argument("address", help="adresse PUBLIQUE (jamais de clé privée)")
    a.add_argument("--label", default="Principal")
    a.add_argument("--group", default="Mon wallet")
    a.add_argument("--no-staking", action="store_true", help="ne pas suivre le staking de cette adresse")
    a.add_argument(
        "--auto-trading", action="store_true", help="compte Hyperliquid de trading automatique (bot)"
    )
    a.set_defaults(func=cmd_wallet_add)
    w.add_parser("list", help="lister les adresses").set_defaults(func=cmd_wallet_list)
    r = w.add_parser("remove", help="ne plus suivre une adresse")
    r.add_argument("id", type=int)
    r.set_defaults(func=cmd_wallet_remove)

    sy = sub.add_parser("sync", help="synchroniser maintenant")
    sy.add_argument(
        "--if-due", action="store_true", help="seulement si la dernière synchronisation est assez ancienne"
    )
    sy.set_defaults(func=cmd_sync)
    st = sub.add_parser("status", help="patrimoine d'après la dernière synchronisation")
    st.add_argument("--eur", action="store_true", help="afficher en euros")
    st.set_defaults(func=cmd_status)
    sub.add_parser("trades", help="statistiques des trades Hyperliquid").set_defaults(func=cmd_trades)
    sv = sub.add_parser("serve", help="lancer l'interface web")
    sv.add_argument(
        "--host", default="127.0.0.1", help="adresse d'écoute (défaut : 127.0.0.1, cette machine seulement)"
    )
    sv.add_argument("--port", type=int, default=8090)
    sv.add_argument(
        "--demo", action="store_true", help="données fictives, aucun appel réseau (dossier data-demo)"
    )
    sv.add_argument("--docker", action="store_true", help=argparse.SUPPRESS)
    sv.set_defaults(func=cmd_serve)
    sub.add_parser("about", help="version, auteur, soutien, configuration").set_defaults(func=cmd_about)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config()
    setup_logging(config, args.verbose)
    return args.func(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
