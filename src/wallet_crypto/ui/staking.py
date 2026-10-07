"""Staking : positions suivies automatiquement (HYPE, WCT, vaults) et positions saisies."""

from __future__ import annotations

from decimal import Decimal

from nicegui import ui

from .. import fmt, services
from ..db.models import ManualStakeRow, ManualStakeTxRow
from .components import (
    Money,
    alert,
    avatar,
    chip,
    confirm,
    dec_input,
    dt_input,
    empty_state,
    kpi,
    money_fmt,
    page_title,
    parse_dec,
    parse_dt,
    when,
)
from .context import ctx


def short_qty(x):
    """Quantité estimée (mode APR) : quatre décimales suffisent à l'affichage."""
    return fmt.number(x, 4).rstrip("0").rstrip(",") if x is not None else "—"


DOW = {0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi", 4: "vendredi", 5: "samedi", 6: "dimanche"}
KIND_LABEL = {
    "DEPOSIT": "Dépôt",
    "WITHDRAW": "Retrait",
    "REWARD": "Récompense",
    "RESTAKE": "Re-lock",
    "DELEG": "Délégation",
    "UNDELEG": "Retrait de délégation",
    "WITHDRAW_REQ": "Demande de retrait",
}
TX_LABEL = {"STAKE": "Dépôt", "UNSTAKE": "Retrait", "REWARD": "Récompense"}
HL_URL = "https://app.hyperliquid.xyz/staking"
WCT_URL = "https://optimistic.etherscan.io/address/0x521B4C065Bbdbe3E20B3727340730936912DfA46"


def _auto_card(a: services.AutoStakeView, m: Money) -> None:
    mt = a.metrics
    with ui.column().classes("wc-card w-full gap-3"):
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-3"):
                avatar(a.asset)
                with ui.column().classes("gap-0"):
                    ui.label(a.asset).classes("wc-section-title")
                    ui.label(a.account).classes("wc-muted text-xs")
                chip(
                    "automatique · délégation Hyperliquid"
                    if a.source == "HL_HYPE"
                    else "automatique · lock WCT (Optimism)"
                )
                ui.link("ouvrir ↗", HL_URL if a.source == "HL_HYPE" else WCT_URL, new_tab=True).classes(
                    "wc-link text-sm"
                )
            ui.label(m(a.value) if a.value is not None else "prix inconnu").classes(
                "text-xl font-semibold wc-num"
            )
        with ui.row().classes("w-full gap-3 flex-wrap"):
            kpi("Staké", fmt.qty(a.staked), f"capital net {fmt.qty(mt.capital)}")
            rew = f"dont {fmt.qty(a.pending)} à réclamer" if a.pending else None
            kpi("Récompenses", fmt.qty(mt.rewards_total), rew)
            kpi("APR réel moyen", fmt.pct(mt.apr_avg, 2, False), "depuis le premier dépôt")
            kpi(
                "APR 30 jours",
                fmt.pct(mt.apr_30, 2, False),
                None if mt.apr_30 is not None else "récompenses à réclamer" if a.source == "WCT_OP" else None,
            )
            kpi(
                "Gain sur capital",
                fmt.pct(mt.gain_pct, 2, False),
                m(mt.rewards_total * a.price) if a.price else None,
            )
        info = []
        if a.source == "HL_HYPE":
            info.append("Récompenses quotidiennes, recomposées automatiquement.")
            if a.line_extra.get("pending_withdrawal"):
                info.append(f"Retrait en cours (7 jours) : {fmt.qty(a.line_extra['pending_withdrawal'])}.")
            if a.line_extra.get("undelegated"):
                info.append(f"Non délégué (ne rapporte rien) : {fmt.qty(a.line_extra['undelegated'])}.")
        else:
            info.append("Récompenses hebdomadaires, à réclamer (pas de recomposition automatique).")
            if a.line_extra.get("permanent"):
                info.append("Lock permanent.")
            elif a.line_extra.get("lock_end"):
                info.append(f"Fin du lock : {when(int(a.line_extra['lock_end']) * 1000, False)}.")
        if mt.restaked:
            info.append(f"Récompenses re-lockées : {fmt.qty(mt.restaked)} (non comptées comme capital).")
        ui.label(" ".join(info)).classes("wc-muted text-sm")
        if not a.events:
            alert(
                "Historique pas encore importé : capital, gain et APR seront calculés après une synchronisation.",
                "info",
            )
        elif mt.ecart is not None and abs(mt.ecart) > max(Decimal("0.0001"), a.staked * Decimal("0.005")):
            alert(
                f"Écart de {fmt.qty(mt.ecart)} entre le staké réel ({fmt.qty(a.staked)}) et l'historique ({fmt.qty(mt.expected)}) : "
                "historique incomplet, dépôt fait par un tiers ou type d'événement inconnu (voir le journal).",
                "warn",
            )
        if a.events:
            with ui.expansion(f"Historique ({len(a.events)} mouvements)").classes("w-full text-sm"):
                with ui.element("table").classes("wc-table"):
                    for e in a.events[:200]:
                        with ui.element("tr"):
                            with ui.element("td").classes("wc-muted"):
                                ui.label(when(e["time_ms"]))
                            with ui.element("td"):
                                ui.label(KIND_LABEL.get(e["kind"], e["kind"]))
                            with ui.element("td").classes("r"):
                                ui.label(fmt.qty(e["qty"]))


def new_position_dialog(refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(560px,95vw)] gap-2"):
        ui.label("Nouvelle position de staking").classes("wc-section-title")
        ui.label(
            "Pour un staking hors de vos wallets suivis (plateforme centralisée, autre protocole)."
        ).classes("wc-muted text-sm")
        crypto = ui.input("Crypto (symbole)").props("outlined dense").classes("w-full")
        start = dt_input("Date de début")
        mode = ui.toggle({"apr": "Taux annoncé (APR)", "rewards": "Récompenses réelles"}, value="apr").props(
            "no-caps"
        )
        qty = dec_input("Quantité stakée au départ")
        apr = dec_input("APR (%)", hint="Taux annuel annoncé, en %")
        period = (
            ui.select(
                {1: "Quotidien", 7: "Hebdomadaire", 30: "Mensuel"}, value=1, label="Versement des récompenses"
            )
            .props("outlined dense")
            .classes("w-full")
        )
        dow = ui.select(DOW, value=0, label="Jour du versement").props("outlined dense").classes("w-full")
        dom = (
            ui.number("Jour du mois (1 à 28)", value=1, min=1, max=28, format="%d")
            .props("outlined dense")
            .classes("w-full")
        )
        restake = ui.switch("Récompenses réintégrées au capital", value=False)
        fee = dec_input("Frais sur les gains (%)", "0")
        url = ui.input("Lien vers la plateforme (facultatif)").props("outlined dense").classes("w-full")
        entry = dec_input("Prix d'entrée moyen en $ (facultatif)")

        def sync_visibility():
            apr.set_visibility(mode.value == "apr")
            restake.set_visibility(mode.value == "rewards")
            dow.set_visibility(period.value == 7)
            dom.set_visibility(period.value == 30)

        mode.on_value_change(lambda _: sync_visibility())
        period.on_value_change(lambda _: sync_visibility())
        sync_visibility()

        def save():
            try:
                services.create_manual_stake(
                    c.db, crypto.value, parse_dt(start.value), mode.value, int(period.value), parse_dec(qty.value),
                    parse_dec(apr.value, True) or Decimal(0), int(dow.value or 0), int(dom.value or 1), restake.value,
                    parse_dec(fee.value, True) or Decimal(0), (url.value or "").strip() or None, parse_dec(entry.value, True),
                )  # fmt: skip
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                return
            c.bump()
            d.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=d.close).props("flat no-caps")
            ui.button("Créer", on_click=save).props("unelevated color=primary no-caps")
    d.open()


def tx_dialog(pos_id: int, crypto: str, kind: str, refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(420px,95vw)] gap-2"):
        ui.label(f"{TX_LABEL[kind]} · {crypto}").classes("wc-section-title")
        t = dt_input("Date")
        qty = dec_input("Quantité")

        def save():
            try:
                services.add_manual_stake_tx(c.db, pos_id, kind, parse_dt(t.value), parse_dec(qty.value))
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                return
            c.bump()
            d.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=d.close).props("flat no-caps")
            ui.button("Enregistrer", on_click=save).props("unelevated color=primary no-caps")
    d.open()


def rate_dialog(pos_id: int, crypto: str, refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(420px,95vw)] gap-2"):
        ui.label(f"Nouveau taux · {crypto}").classes("wc-section-title")
        ui.label("Le taux en cours s'arrête à cette date.").classes("wc-muted text-sm")
        t = dt_input("À partir du")
        apr = dec_input("APR (%)")

        def save():
            try:
                services.add_manual_stake_rate(c.db, pos_id, parse_dt(t.value), parse_dec(apr.value))
            except ValueError as exc:
                ui.notify(str(exc), type="negative")
                return
            c.bump()
            d.close()
            refresh()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annuler", on_click=d.close).props("flat no-caps")
            ui.button("Enregistrer", on_click=save).props("unelevated color=primary no-caps")
    d.open()


def _manual_card(v: services.ManualStakeView, m: Money, refresh) -> None:
    c = ctx()
    p, mt = v.row, v.metrics
    with ui.column().classes("wc-card w-full gap-3"):
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-3 flex-wrap"):
                avatar(p.crypto)
                with ui.column().classes("gap-0"):
                    ui.label(p.crypto).classes("wc-section-title")
                    ui.label(
                        f"depuis le {when(p.start_ms, False)}"
                        + ("" if p.active else f" · terminé le {when(p.end_ms, False)}")
                    ).classes("wc-muted text-xs")
                chip("taux annoncé" if p.mode == "apr" else "récompenses réelles")
                if v.duplicate:
                    chip("⚠ doublon : déjà suivi automatiquement, exclu des totaux")
                if p.platform_url:
                    ui.link("plateforme ↗", p.platform_url, new_tab=True).classes("wc-link text-sm")
            ui.label(m(v.value) if v.value is not None else "prix inconnu").classes(
                "text-xl font-semibold wc-num"
            )
        with ui.row().classes("w-full gap-3 flex-wrap"):
            kpi("Capital net", short_qty(mt.deposited))
            kpi(
                "Détenu",
                short_qty(mt.held_qty),
                f"dont {short_qty(mt.pocket)} de récompenses à part" if mt.pocket else None,
            )
            sub = fmt.pct(mt.gain_pct) + (f" · frais {short_qty(mt.fee_amount)}" if mt.fee_amount else "")
            kpi("Gain", short_qty(mt.gain), sub)
            if p.mode == "apr":
                kpi(
                    "APR en cours",
                    fmt.pct(mt.apr_current, 2, False),
                    f"prochain versement {when(v.next_reward_ms, False)}" if v.next_reward_ms else None,
                )
            if mt.gain_value is not None:
                kpi(
                    "Gain en valeur",
                    m(mt.gain_value, True),
                    fmt.pct(mt.gain_value_pct),
                    "wc-pos" if mt.gain_value >= 0 else "wc-neg",
                )
        with ui.row().classes("gap-1 flex-wrap"):
            for kind in ("STAKE", "UNSTAKE") + (("REWARD",) if p.mode == "rewards" else ()):
                ui.button(
                    TX_LABEL[kind], on_click=lambda k=kind: tx_dialog(p.id, p.crypto, k, refresh)
                ).props("outline no-caps dense padding='3px 12px'")
            if p.mode == "apr":
                ui.button("Changer le taux", on_click=lambda: rate_dialog(p.id, p.crypto, refresh)).props(
                    "outline no-caps dense padding='3px 12px'"
                )
            if p.active:
                ui.button(
                    "Terminer",
                    on_click=lambda: (
                        services.end_manual_stake(c.db, p.id, services.store.now_ms()),
                        c.bump(),
                        refresh(),
                    ),
                ).props("flat no-caps dense padding='3px 10px'")
            else:
                ui.button(
                    "Réactiver",
                    on_click=lambda: (services.end_manual_stake(c.db, p.id, None), c.bump(), refresh()),
                ).props("flat no-caps dense padding='3px 10px'")
            ui.button(
                "Supprimer",
                on_click=lambda: confirm(
                    "Supprimer cette position ?", "Ses mouvements et ses taux sont supprimés.",
                    lambda: (services.delete_row(c.db, ManualStakeRow, p.id), c.bump(), refresh()),
                ),
            ).props("flat no-caps dense padding='3px 10px' color=negative")  # fmt: skip
        if v.txs:
            with ui.expansion(f"Mouvements ({len(v.txs)})").classes("w-full text-sm"):
                with ui.element("table").classes("wc-table"):
                    for t in reversed(v.txs):
                        with ui.element("tr"):
                            with ui.element("td").classes("wc-muted"):
                                ui.label(when(t.time_ms))
                            with ui.element("td"):
                                ui.label(TX_LABEL.get(t.kind, t.kind))
                            with ui.element("td").classes("r"):
                                ui.label(fmt.qty(t.qty))
                            with ui.element("td").classes("r"):
                                ui.button(
                                    icon="delete",
                                    on_click=lambda tid=t.id: (
                                        services.delete_row(c.db, ManualStakeTxRow, tid),
                                        c.bump(),
                                        refresh(),
                                    ),
                                ).props("flat dense round size=sm").tooltip("Supprimer ce mouvement")


def render(go_to) -> None:
    c = ctx()
    m = money_fmt()
    v = services.staking_view(c.db, c.config, c.price_fn())

    def refresh():
        go_to("staking")

    with ui.row().classes("w-full items-end justify-between gap-3 flex-wrap"):
        page_title("Staking", "Rendement réel calculé sur l'historique on-chain.")
        with ui.row().classes("gap-3"):
            kpi("Automatique", m(v.total_auto))
            kpi("Saisi", m(v.total_manual))
    if not v.autos and not v.vaults:
        alert(
            "Aucun staking détecté dans vos wallets. Pris en charge : délégation HYPE (Hyperliquid), lock WCT (Optimism), "
            "vaults Hyperliquid. Vérifiez « Suivre le staking » sur le wallet.",
            "info",
        )
    for a in v.autos:
        _auto_card(a, m)
    if v.vaults:
        with ui.row().classes("wc-card w-full items-center justify-between"):
            with ui.row().classes("items-center gap-3"):
                avatar("HLP")
                ui.label("Vaults Hyperliquid").classes("font-semibold")
            ui.label(m(v.vaults)).classes("font-semibold wc-num")
    with ui.row().classes("w-full items-center justify-between mt-4"):
        ui.label("Positions saisies").classes("wc-section-title")
        ui.button("Nouvelle position", icon="add", on_click=lambda: new_position_dialog(refresh)).props(
            "unelevated color=primary no-caps"
        )
    if not v.manuals:
        empty_state(
            "Aucune position saisie. Ajoutez ici un staking fait sur une plateforme centralisée ou un autre protocole."
        )
    for mv in v.manuals:
        _manual_card(mv, m, refresh)
