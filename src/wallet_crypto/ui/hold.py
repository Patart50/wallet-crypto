"""Hold : quantité réelle, prix moyen pondéré, latent, réalisé et historique du prix moyen."""

from __future__ import annotations

from nicegui import ui

from .. import fmt, services
from ..db.models import HoldTxRow
from .components import (
    Money,
    alert,
    avatar,
    confirm,
    dec_input,
    dt_input,
    empty_state,
    kpi,
    money_fmt,
    page_title,
    parse_dec,
    parse_dt,
    sign_class,
    when,
)
from .context import ctx

KIND = {
    "BUY": ("Achat", "wc-pos"),
    "SELL": ("Vente", "wc-neg"),
    "FEE": ("Frais de transfert", "wc-warn"),
    "OUT": ("→ staking", "wc-muted"),
    "IN": ("← staking", "wc-muted"),
}
SRC = {"hl_spot": "Hyperliquid spot", "manuel": "saisie", "staking": "staking"}
STATE = {"include_staked": True}


def tx_dialog(refresh, crypto: str = "", side: str = "BUY", qty=None) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(460px,95vw)] gap-2"):
        ui.label("Mouvement pour le prix de revient").classes("wc-section-title")
        ui.label(
            "Pour ce qui ne vient pas d'un achat spot Hyperliquid : achat sur une plateforme, un DEX, transfert reçu. "
            "La quantité affichée reste celle de vos wallets."
        ).classes("wc-muted text-sm")
        cr = ui.input("Crypto (symbole)", value=crypto).props("outlined dense").classes("w-full")
        sd = ui.toggle({"BUY": "Achat", "SELL": "Vente", "FEE": "Frais de transfert"}, value=side).props(
            "no-caps"
        )
        t = dt_input("Date")
        q = dec_input("Quantité", qty)
        px = dec_input("Prix unitaire en $")

        def fill_price():
            p = c.prices.usd((cr.value or "").upper())
            if p:
                px.value = fmt.number(p, 6).replace(" ", "")
            else:
                ui.notify("Prix du jour indisponible : saisissez-le.", type="warning")

        ui.button("Prix du jour", icon="bolt", on_click=fill_price).props(
            "flat no-caps dense padding='3px 10px'"
        )
        ui.label("Frais de transfert : la quantité sort, le coût reste (le prix moyen monte).").classes(
            "wc-muted text-xs"
        )
        px.bind_visibility_from(sd, "value", backward=lambda v: v != "FEE")

        def save():
            try:
                services.add_hold_tx(
                    c.db,
                    cr.value,
                    sd.value,
                    parse_dt(t.value),
                    parse_dec(q.value),
                    parse_dec(px.value, True) or parse_dec("0"),
                )
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


def _card(card: services.HoldCard, m: Money, refresh) -> None:
    pos = card.position
    tol = max(fmt.Decimal("1e-9"), (max(pos.real, pos.inv_qty)) / 1000)
    with ui.column().classes("wc-card w-full gap-3"):
        with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
            with ui.row().classes("items-center gap-3"):
                avatar(card.base)
                with ui.column().classes("gap-0"):
                    ui.label(card.base).classes("wc-section-title")
                    ui.label(f"{card.n_hl} achat(s) Hyperliquid · {card.n_manual} saisie(s)").classes(
                        "wc-muted text-xs"
                    )
            ui.label(
                m(pos.value) if pos.value is not None else ("non détenu" if not card.held else "prix inconnu")
            ).classes("text-xl font-semibold wc-num")
        with ui.row().classes("w-full gap-3 flex-wrap"):
            if card.held:
                sub = f"dont {fmt.qty(card.staked, card.price)} staké" if card.staked else None
                kpi("Détenu", fmt.qty(pos.real, card.price), sub)
                kpi("Prix", fmt.number(card.price, 4) + " $" if card.price else "—")
            cov = None
            if pos.coverage_pct is not None and pos.coverage_pct < fmt.Decimal("99.5"):
                cov = f"sur {fmt.number(pos.coverage_pct, 0)} % du détenu"
            kpi("Prix moyen", fmt.number(pos.pmp, 4) + " $" if pos.covered > 0 else "—", cov)
            if pos.latent is not None:
                kpi("Latent", m(pos.latent, True), fmt.pct(pos.latent_pct), sign_class(pos.latent))
            if pos.realized:
                kpi("Réalisé", m(pos.realized, True), None, sign_class(pos.realized))
        if pos.from_rewards > tol:
            ui.label(
                f"Dont {fmt.qty(pos.from_rewards)} de récompenses de staking (coût nul, déjà comptées comme gain dans Staking)."
            ).classes("wc-muted text-sm")
        if card.held and pos.unknown > tol:
            alert(
                f"{fmt.qty(pos.unknown)} sans prix d'achat connu (transfert, airdrop, achat hors Hyperliquid) : ajoutez un achat pour compléter le prix moyen."
            )
        if not card.held and pos.inv_qty > tol:
            alert(f"{fmt.qty(pos.inv_qty)} achetés d'après vos saisies mais absents des wallets suivis.")
        if pos.oversold > tol:
            alert(f"Ventes supérieures aux achats connus de {fmt.qty(pos.oversold)} : un achat manque.")
        if card.held and pos.excess > tol:
            with ui.row().classes("w-full items-center gap-2"):
                alert(
                    f"Achats enregistrés supérieurs au détenu de {fmt.qty(pos.excess)} : frais de transfert, doublon entre saisie et "
                    "achats Hyperliquid, ou vente non saisie."
                )
                ui.button(
                    "Marquer comme frais de transfert",
                    on_click=lambda: tx_dialog(refresh, card.base, "FEE", pos.excess),
                ).props("outline no-caps dense padding='3px 12px'")
        with ui.row().classes("gap-1"):
            ui.button("Achat", on_click=lambda: tx_dialog(refresh, card.base, "BUY")).props(
                "outline no-caps dense padding='3px 12px'"
            )
            ui.button("Vente", on_click=lambda: tx_dialog(refresh, card.base, "SELL")).props(
                "outline no-caps dense padding='3px 12px'"
            )
            ui.button("Frais", on_click=lambda: tx_dialog(refresh, card.base, "FEE")).props(
                "outline no-caps dense padding='3px 12px'"
            )
        if pos.history:
            with ui.expansion(f"Historique du prix moyen ({len(pos.history)} mouvements)").classes(
                "w-full text-sm"
            ):
                with ui.element("table").classes("wc-table"):
                    with ui.element("tr"):
                        for h, cls in (
                            ("Date", ""),
                            ("Opération", ""),
                            ("Source", ""),
                            ("Quantité", "r"),
                            ("Prix", "r"),
                            ("Prix moyen", "r"),
                            ("Effet", "r"),
                        ):
                            with ui.element("th").classes(cls).props('scope="col"'):
                                ui.label(h)
                    for h in list(reversed(pos.history))[:200]:
                        lab, cls = KIND.get(h["kind"], (h["kind"], ""))
                        with ui.element("tr"):
                            with ui.element("td").classes("wc-muted"):
                                ui.label(when(h["time_ms"]))
                            with ui.element("td"):
                                ui.label(lab).classes(cls)
                            with ui.element("td").classes("wc-muted"):
                                ui.label(SRC.get(h["src"], h["src"] or ""))
                            with ui.element("td").classes("r"):
                                ui.label(fmt.qty(h["qty"], h["price"] or h["pmp_after"] or None))
                            with ui.element("td").classes("r"):
                                ui.label(fmt.number(h["price"], 4) if h["price"] else "—")
                            with ui.element("td").classes("r"):
                                ui.label(
                                    f"{fmt.number(h['pmp_before'], 4)} → {fmt.number(h['pmp_after'], 4)}"
                                )
                            with ui.element("td").classes("r"):
                                if h["kind"] == "SELL":
                                    ui.label(f"réalisé {m(h['realized'], True)}").classes(
                                        sign_class(h["realized"])
                                    )
                                elif h["kind"] in ("BUY", "FEE") and h["pmp_before"]:
                                    d = (h["pmp_after"] - h["pmp_before"]) / h["pmp_before"] * 100
                                    ui.label(f"prix moyen {fmt.pct(d)}").classes("wc-muted")
                                else:
                                    ui.label("—").classes("wc-muted")


def render(go_to) -> None:
    c = ctx()
    m = money_fmt()

    def refresh():
        go_to("hold")

    v = services.hold_view(c.db, c.price_fn(), STATE["include_staked"])
    with ui.row().classes("w-full items-end justify-between gap-3 flex-wrap"):
        page_title("Hold", "Quantités réelles de vos wallets, prix moyen reconstitué à partir de vos achats.")
        with ui.row().classes("items-center gap-3"):
            sw = ui.switch("Inclure le staké", value=STATE["include_staked"]).tooltip(
                "Ajoute le staké et le réclamable à la quantité : latent de toute la position. Vue seulement : le patrimoine ne compte rien deux fois."
            )
            sw.on_value_change(lambda e: (STATE.update(include_staked=e.value), refresh()))
            ui.button("Mouvement", icon="add", on_click=lambda: tx_dialog(refresh)).props(
                "unelevated color=primary no-caps"
            )
    with ui.row().classes("w-full gap-3 flex-wrap"):
        kpi("Valeur", m(v.total_value))
        kpi("Latent (part au prix connu)", m(v.total_latent, True), None, sign_class(v.total_latent))
        kpi("Réalisé cumulé", m(v.total_realized, True), None, sign_class(v.total_realized))
    if v.skipped_pairs:
        ui.label(
            f"Paires spot Hyperliquid ignorées (cotation non stable) : {', '.join(v.skipped_pairs)}."
        ).classes("wc-muted text-xs")
    if not v.cards and not v.gone:
        empty_state("Aucun token en hold dans vos wallets.")
    for card in v.cards:
        _card(card, m, refresh)
    if v.gone:
        with ui.expansion(f"{len(v.gone)} crypto(s) soldée(s) ou hors des wallets suivis").classes(
            "w-full wc-card"
        ):
            for card in v.gone:
                _card(card, m, refresh)
    if v.manual_txs:
        with ui.expansion(f"Vos saisies ({len(v.manual_txs)})").classes("w-full wc-card"):
            with ui.element("table").classes("wc-table text-sm"):
                for t in reversed(v.manual_txs):
                    with ui.element("tr"):
                        with ui.element("td").classes("wc-muted"):
                            ui.label(when(t.time_ms))
                        with ui.element("td"):
                            ui.label(f"{KIND[t.side][0]} {t.crypto}")
                        with ui.element("td").classes("r"):
                            ui.label(fmt.qty(t.qty, t.price or None))
                        with ui.element("td").classes("r"):
                            ui.label(fmt.number(t.price, 4) + " $" if t.side != "FEE" else "—")
                        with ui.element("td").classes("r"):
                            ui.button(
                                icon="delete",
                                on_click=lambda tid=t.id: confirm(
                                    "Supprimer cette saisie ?", "Le prix moyen sera recalculé.",
                                    lambda: (services.delete_row(c.db, HoldTxRow, tid), c.bump(), refresh()),
                                ),
                            ).props("flat dense round size=sm")  # fmt: skip
