"""Wallets : adresses suivies, soldes réels, comptes Hyperliquid et positions ouvertes."""

from __future__ import annotations

from nicegui import ui

from .. import fmt, services
from ..money import ZERO
from ..security import NETWORKS
from .components import (
    Money,
    ago,
    alert,
    avatar,
    chip,
    confirm,
    empty_state,
    money_fmt,
    page_title,
    short_addr,
    sign_class,
)
from .context import ctx

NETWORK_LABELS = {"HL": "Hyperliquid", "EVM": "EVM", "SOL": "Solana", "BTC": "Bitcoin"}
LINE_LABEL = {"_STAKED": " staké", "_PENDING": " à réclamer", "_SPOT": " spot"}


def line_label(coin: str, network: str, extra: dict) -> str:
    if coin == "USDC" and network == "HL":
        return "USDC (compte unifié)" if (extra or {}).get("mode") == "unified" else "Equity perp"
    if coin == "HLP_VAULTS":
        return "Vaults HLP"
    for suf, lab in LINE_LABEL.items():
        if coin.endswith(suf):
            return coin[: -len(suf)] + lab
    return coin


def add_dialog(refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(560px,95vw)] gap-3"):
        ui.label("Ajouter des adresses").classes("wc-section-title")
        ui.label(
            "Adresses publiques uniquement. Une même adresse 0x peut être suivie sur Hyperliquid et en EVM : cochez les deux."
        ).classes("wc-muted text-sm")
        nets = (
            ui.select(
                {n: NETWORK_LABELS[n] for n in NETWORKS}, value=["HL", "EVM"], multiple=True, label="Réseaux"
            )
            .props("outlined dense use-chips")
            .classes("w-full")
        )
        addrs = ui.textarea("Adresses (une par ligne)").props("outlined autogrow").classes("w-full wc-mono")
        with ui.row().classes("w-full gap-3 no-wrap"):
            group = ui.input("Groupe", value="Mon wallet").props("outlined dense").classes("flex-1")
            label = ui.input("Nom", value="Principal").props("outlined dense").classes("flex-1")
        track = ui.switch("Suivre le staking", value=True)
        auto = ui.switch("Compte de trading automatique (bot)", value=False).tooltip(
            "Hyperliquid uniquement : sépare le trading automatique du trading manuel dans les gains et les graphiques."
        )
        errs = ui.column().classes("w-full gap-1")

        def save():
            errs.clear()
            added, errors = services.add_wallets(
                c.db,
                list(nets.value or []),
                (addrs.value or "").splitlines(),
                group.value,
                label.value,
                track.value,
                auto.value,
            )
            with errs:
                for e in errors:
                    alert(e, "err")
            if added:
                ui.notify(f"{len(added)} adresse(s) ajoutée(s). Lancez une synchronisation.", type="positive")
                c.bump()
                refresh()
                if not errors:
                    d.close()
            elif not errors:
                with errs:
                    alert("Aucune adresse saisie.", "warn")
            if any(n in ("EVM", "SOL") for n in (nets.value or [])) and not c.config.alchemy_key:
                with errs:
                    alert("Sans clé Alchemy, les wallets EVM et Solana ne seront pas lus (Réglages).", "info")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Fermer", on_click=d.close).props("flat no-caps")
            ui.button("Ajouter", icon="add", on_click=save).props("unelevated color=primary no-caps")
    d.open()


def edit_dialog(w: services.WalletView, refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(480px,95vw)] gap-3"):
        ui.label(f"{NETWORK_LABELS[w.network]} · {short_addr(w.address)}").classes("wc-section-title")
        group = ui.input("Groupe", value=w.group).props("outlined dense").classes("w-full")
        label = ui.input("Nom", value=w.label).props("outlined dense").classes("w-full")
        track = ui.switch("Suivre le staking", value=w.track_staking)
        auto = ui.switch("Compte de trading automatique (bot)", value=w.auto_trading)
        if w.network != "HL":
            auto.disable()
        active = ui.switch("Synchroniser cette adresse", value=w.is_active)

        def save():
            services.update_wallet(
                c.db, w.id, group_name=group.value.strip() or "Mon wallet", label=label.value.strip() or "Principal",
                track_staking=track.value, auto_trading=auto.value, is_active=active.value,
            )  # fmt: skip
            c.bump()
            d.close()
            refresh()

        def remove():
            def yes():
                services.delete_wallet(c.db, w.id)
                c.bump()
                d.close()
                refresh()

            confirm(
                "Ne plus suivre cette adresse ?",
                "Ses soldes, ses positions, son historique importé (fills, funding, staking) et sa part dans "
                "les relevés passés du patrimoine sont retirés. Pour l'arrêter sans rien effacer, "
                "décochez plutôt « Synchroniser cette adresse ».",
                yes,
            )

        with ui.row().classes("w-full justify-between"):
            ui.button("Supprimer", icon="delete", on_click=remove).props("flat color=negative no-caps")
            with ui.row().classes("gap-2"):
                ui.button("Annuler", on_click=d.close).props("flat no-caps")
                ui.button("Enregistrer", on_click=save).props("unelevated color=primary no-caps")
    d.open()


def _hl_detail(w: services.WalletView, m: Money) -> None:
    ex = w.usdc_extra or {}
    if ex:
        unified = ex.get("mode") == "unified"
        with ui.row().classes("gap-2 flex-wrap items-center text-sm"):
            chip(
                "compte unifié" if unified else "compte standard",
                "Détecté automatiquement (mode de compte Hyperliquid).",
            )
            if unified:
                chip(f"transférable {m(ex.get('transferable'))}")
            elif ex.get("withdrawable") is not None:
                chip(f"retirable {m(ex.get('withdrawable'))}")
            chip(f"marge engagée {m(ex.get('margin_used'))}")
            upnl = ex.get("upnl")
            ui.html(
                f'<span class="wc-chip">PnL latent&nbsp;<span class="{sign_class(upnl)}">{m(upnl, True)}</span></span>'
            )
            off = ex.get("official_value")
            if off is not None:
                gap = off - w.total
                ok = abs(gap) <= max(1, abs(off) * 5 / 1000)
                chip(
                    f"{'✓' if ok else '⚠'} valeur Hyperliquid {m(off)}",
                    "Valeur du compte publiée par Hyperliquid, comparée au total calculé ici. "
                    + ("Concordant." if ok else f"Écart de {m(gap, True)} : à signaler."),
                )
    if w.positions:
        n = len(w.positions)
        ui.link(
            f"{n} position{'s' if n > 1 else ''} ouverte{'s' if n > 1 else ''} : voir Trades", "/trades"
        ).classes("wc-link text-sm")


def _table_header(cols: list[tuple[str, str]]) -> None:
    with ui.element("tr"):
        for h, cls in cols:
            with ui.element("th").classes(cls).props('scope="col"'):
                ui.label(h)


def render(go_to) -> None:
    c = ctx()
    m = money_fmt()
    groups = services.wallets_view(c.db, c.price_fn())

    with ui.row().classes("w-full items-end justify-between gap-3 flex-wrap"):
        page_title("Wallets", "Soldes réels de chaque adresse à la dernière synchronisation.")
        ui.button(
            "Ajouter des adresses", icon="add", on_click=lambda: add_dialog(lambda: go_to("wallets"))
        ).props("unelevated color=primary no-caps")
    if not groups:
        empty_state(
            "Aucune adresse suivie pour l'instant.",
            "Ajouter des adresses",
            lambda: add_dialog(lambda: go_to("wallets")),
        )
        return
    grand = sum((w.total for ws in groups.values() for w in ws), ZERO)
    ui.label(f"Total des wallets : {m(grand)}").classes("wc-muted text-sm")
    for group, wallets in groups.items():
        with ui.column().classes("wc-card w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(group).classes("wc-section-title")
                ui.label(m(sum((w.total for w in wallets), ZERO))).classes("font-semibold wc-num")
            for w in wallets:
                with ui.column().classes("wc-card-2 w-full gap-2"):
                    with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                        with ui.row().classes("items-center gap-2 flex-wrap"):
                            chip(NETWORK_LABELS[w.network])
                            ui.label(w.label).classes("font-semibold")
                            addr = (
                                ui.label(short_addr(w.address))
                                .classes("wc-mono wc-muted cursor-pointer")
                                .tooltip(f"{w.address} (cliquer pour copier)")
                            )
                            addr.on(
                                "click",
                                lambda a=w.address: (ui.clipboard.write(a), ui.notify("Adresse copiée")),
                            )
                            if w.auto_trading:
                                chip("trading automatique")
                            if not w.is_active:
                                chip("en pause")
                            ui.label(f"synchronisé {ago(w.last_sync_ms)}").classes("wc-muted text-xs")
                        with ui.row().classes("items-center gap-2"):
                            ui.label(m(w.total)).classes("font-semibold wc-num")
                            ui.button(
                                icon="edit", on_click=lambda ww=w: edit_dialog(ww, lambda: go_to("wallets"))
                            ).props("flat dense round").tooltip("Modifier")
                    if w.last_error:
                        alert(
                            f"Dernière synchronisation en échec (anciens soldes conservés) : {w.last_error}",
                            "err",
                        )
                    if not w.lines and not w.last_error:
                        ui.label("Pas encore synchronisé." if not w.last_sync_ms else "Aucun solde.").classes(
                            "wc-muted text-sm"
                        )
                    if w.lines:
                        with ui.element("table").classes("wc-table text-sm"):
                            _table_header([("Actif", ""), ("Quantité", "r"), ("Prix", "r"), ("Valeur", "r")])
                            for ln in w.lines:
                                with ui.element("tr"):
                                    with ui.element("td"), ui.row().classes("items-center gap-2 no-wrap"):
                                        avatar(ln.coin, 26)
                                        lab = ui.label(line_label(ln.coin, w.network, ln.extra))
                                        chains = (ln.extra or {}).get("chains")
                                        if chains:
                                            lab.tooltip(
                                                " · ".join(
                                                    f"{k.replace('-mainnet', '')} {fmt.qty(v)}"
                                                    for k, v in chains.items()
                                                )
                                            )
                                    with ui.element("td").classes("r"):
                                        ui.label(fmt.qty(ln.qty, ln.price or None))
                                    with ui.element("td").classes("r wc-muted"):
                                        ui.label(
                                            fmt.number(ln.price, 4) if ln.price and not ln.unpriced else "—"
                                        )
                                    with ui.element("td").classes("r"):
                                        ui.label("prix inconnu" if ln.unpriced else m(ln.value)).classes(
                                            "wc-warn" if ln.unpriced else ""
                                        )
                    if w.network == "HL":
                        _hl_detail(w, m)
