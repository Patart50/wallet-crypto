"""Trades : Hyperliquid (importés automatiquement) et autres plateformes (saisis)."""

from __future__ import annotations

from decimal import Decimal

from nicegui import ui

from .. import fmt, services
from ..db.models import ManualTradeRow
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
    sign_class,
    when,
)
from .context import ctx

PERIODS = {0: "Tout", 7: "7 jours", 30: "30 jours", 90: "90 jours", 365: "1 an"}
STATE: dict = {"accounts": None, "period": 0}
VISIBLE = 5


def _dur(minutes: Decimal | None) -> str:
    if minutes is None:
        return "—"
    mn = float(minutes)
    if mn < 60:
        return f"{mn:.0f} min"
    if mn < 48 * 60:
        return f"{mn / 60:.1f} h".replace(".", ",")
    return f"{mn / 1440:.1f} j".replace(".", ",")


def _stats_row(st: dict, m: Money, big: bool = False) -> None:
    cols = "grid-cols-2 sm:grid-cols-4 xl:grid-cols-7" if big else "grid-cols-2 sm:grid-cols-5"
    with ui.element("div").classes(f"w-full grid gap-3 {cols}"):
        kpi(
            "Résultat net",
            m(st["net"], True),
            f"frais {m(st['fees'])} · funding {m(st['funding'], True)}",
        )
        kpi("Trades clos", str(st["n"]), f"{st['n_open']} ouvert(s)" if st["n_open"] else None)
        kpi("Winrate", fmt.pct(st["wr"], 1, False))
        kpi("Profit factor", fmt.number(st["pf"]))
        kpi("Espérance", m(st["expectancy"], True), "par trade")
        if big:
            kpi("Gain moyen", m(st["avg_win"], True), None, "wc-pos")
            kpi("Perte moyenne", m(st["avg_loss"], True), None, "wc-neg")
    if big and st["wr"] is not None and st["wr"] >= 50 and (st["expectancy"] or 0) < 0:
        alert(
            "Winrate supérieur à 50 % mais espérance négative : les pertes moyennes dépassent les gains moyens."
        )


def _trade_table(trades: list[dict], m: Money, live: dict) -> None:
    with ui.element("table").classes("wc-table text-sm"):
        with ui.element("tr"):
            for h, cls in (
                ("Ouverture → clôture", ""),
                ("Durée", ""),
                ("Sens", ""),
                ("Taille", "r"),
                ("Entrée → sortie", "r"),
                ("Net", "r"),
            ):
                with ui.element("th").classes(cls).props('scope="col"'):
                    ui.label(h)
        for t in trades:
            is_open = t["close_time"] is None
            with ui.element("tr"):
                with ui.element("td").classes("wc-muted"):
                    ui.label(f"{when(t['open_time'])} → {'en cours' if is_open else when(t['close_time'])}")
                with ui.element("td").classes("wc-muted"):
                    ui.label(_dur(t["duration_min"]))
                with ui.element("td"):
                    ui.label(t["side"]).classes("wc-pos" if t["side"] == "LONG" else "wc-neg")
                with ui.element("td").classes("r"):
                    ui.label(
                        fmt.qty(t["qty_open"] if is_open else t["size_max"], t["entry_px"] or t["exit_px"])
                    )
                with ui.element("td").classes("r"):
                    ui.label(
                        f"{fmt.number(t['entry_px'], 4)}"
                        + ("" if is_open else f" → {fmt.number(t['exit_px'], 4)}")
                    )
                with ui.element("td").classes("r"):
                    flags = []
                    if t["incomplete"]:
                        flags.append("incomplet")
                    if t["liquidated"]:
                        flags.append("liquidé")
                    if t["gap"]:
                        flags.append("fills manquants")
                    if is_open:
                        lv = live.get((t["account"], t["coin"]))
                        txt = f"latent {m(lv['upnl'], True)}" if lv else "ouvert"
                        ui.label(txt).classes(sign_class(lv["upnl"]) if lv else "wc-muted")
                    else:
                        lab = ui.label(
                            m(t["net"], True)
                            + (f" ({fmt.pct(t['ret_pct'])})" if t["ret_pct"] is not None else "")
                        ).classes(sign_class(t["net"]))
                        lab.tooltip(
                            f"PnL de prix {m(t['closed_pnl'], True)} · frais −{m(t['fees'])} · funding {m(t['funding'], True)} · {t['n_fills']} fill(s)"
                        )
                    if flags:
                        ui.label(" · ".join(flags)).classes("wc-warn text-xs").tooltip(
                            "Incomplet : déjà ouvert avant le premier fill disponible chez Hyperliquid (10 000 au plus)."
                        )


def manual_dialog(refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(480px,95vw)] gap-2"):
        ui.label("Nouveau trade (autre plateforme)").classes("wc-section-title")
        ui.label(
            "Les trades Hyperliquid sont importés automatiquement : ne les ressaisissez pas ici."
        ).classes("wc-muted text-sm")
        cr = ui.input("Crypto (symbole)").props("outlined dense").classes("w-full")
        plat = ui.input("Plateforme (facultatif)").props("outlined dense").classes("w-full")
        dirn = ui.toggle({"LONG": "Long", "SHORT": "Short"}, value="LONG").props("no-caps")
        lev = dec_input("Levier", "1")
        t = dt_input("Ouverture")
        q = dec_input("Quantité (levier compris)")
        px = dec_input("Prix d'entrée en $")

        def save():
            try:
                services.create_manual_trade(
                    c.db,
                    cr.value,
                    dirn.value,
                    parse_dec(lev.value),
                    parse_dt(t.value),
                    parse_dec(q.value),
                    parse_dec(px.value),
                    plat.value,
                )
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


def manual_tx_dialog(v: services.ManualTradeView, kind: str, refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(420px,95vw)] gap-2"):
        ui.label(f"{'Renforcer' if kind == 'ADD' else 'Réduire'} · {v.row.crypto} {v.row.direction}").classes(
            "wc-section-title"
        )
        t = dt_input("Date")
        q = dec_input("Quantité", v.metrics["qty"] if kind == "REDUCE" else None)
        px = dec_input("Prix en $", v.price)

        def save():
            try:
                services.add_manual_trade_tx(
                    c.db, v.row.id, kind, parse_dt(t.value), parse_dec(q.value), parse_dec(px.value)
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


def override_dialog(v: services.ManualTradeView, refresh) -> None:
    c = ctx()
    with ui.dialog() as d, ui.card().classes("wc-card w-[min(420px,95vw)] gap-2"):
        ui.label("PnL réalisé réel").classes("wc-section-title")
        ui.label("Montant affiché par la plateforme (frais et funding compris). Vide = PnL calculé.").classes(
            "wc-muted text-sm"
        )
        val = dec_input("PnL réalisé en $", v.row.pnl_override)

        def save():
            try:
                services.set_manual_trade_override(c.db, v.row.id, parse_dec(val.value, True))
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


def _manual_section(m: Money, refresh) -> None:
    c = ctx()
    views = services.manual_trades_view(c.db, c.price_fn())
    with ui.row().classes("w-full items-center justify-between mt-6"):
        ui.label("Trades sur d'autres plateformes").classes("wc-section-title")
        ui.button("Nouveau trade", icon="add", on_click=lambda: manual_dialog(refresh)).props(
            "unelevated color=primary no-caps"
        )
    if not views:
        empty_state("Aucun trade saisi. En attendant les connecteurs de plateformes, saisissez-les ici.")
        return
    for v in views:
        mt = v.metrics
        with ui.column().classes("wc-card w-full gap-2"):
            with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                with ui.row().classes("items-center gap-2 flex-wrap"):
                    avatar(v.row.crypto, 28)
                    ui.label(v.row.crypto).classes("font-semibold")
                    ui.label(v.row.direction).classes("wc-pos" if v.row.direction == "LONG" else "wc-neg")
                    chip(f"×{fmt.number(v.row.leverage, 1)}")
                    if v.row.platform:
                        chip(v.row.platform)
                    if mt["closed"]:
                        chip("soldé")
                    ui.label(f"ouvert le {when(v.row.open_ms, False)}").classes("wc-muted text-xs")
                ui.label(m(mt["realized"], True) + (" ✎" if mt["override"] is not None else "")).classes(
                    f"font-semibold {sign_class(mt['realized'])}"
                )
            with ui.row().classes("w-full gap-3 flex-wrap"):
                kpi("Quantité", fmt.qty(mt["qty"], mt["pmp"] or None))
                kpi("Prix moyen", fmt.number(mt["pmp"], 4) if mt["qty"] else "—")
                kpi("Marge", m(mt["margin"]))
                if not mt["closed"]:
                    kpi(
                        "Latent",
                        m(mt["latent"], True) if mt["latent"] is not None else "prix inconnu",
                        fmt.pct(mt["roe"]) + " ROE" if mt["roe"] is not None else None,
                        sign_class(mt["latent"]),
                    )
            with ui.row().classes("gap-1"):
                if not mt["closed"]:
                    ui.button("Renforcer", on_click=lambda vv=v: manual_tx_dialog(vv, "ADD", refresh)).props(
                        "outline no-caps dense padding='3px 12px'"
                    )
                    ui.button("Réduire", on_click=lambda vv=v: manual_tx_dialog(vv, "REDUCE", refresh)).props(
                        "outline no-caps dense padding='3px 12px'"
                    )
                ui.button("PnL réel", on_click=lambda vv=v: override_dialog(vv, refresh)).props(
                    "flat no-caps dense padding='3px 10px'"
                )
                ui.button(
                    "Supprimer",
                    on_click=lambda vv=v: confirm(
                        "Supprimer ce trade ?", "Tous ses mouvements sont supprimés.",
                        lambda: (services.delete_row(c.db, ManualTradeRow, vv.row.id), c.bump(), refresh()),
                    ),
                ).props("flat no-caps dense padding='3px 10px' color=negative")  # fmt: skip


def render(go_to) -> None:
    c = ctx()
    m = money_fmt()

    def refresh():
        go_to("trades")

    accounts = services.hl_accounts(c.db)
    with ui.row().classes("w-full items-end justify-between gap-3 flex-wrap"):
        page_title(
            "Trades",
            "Reconstruits à partir des fills Hyperliquid. Statistiques nettes de frais et de funding.",
        )
    if accounts:
        tv = services.trades_view(c.db, STATE["accounts"], STATE["period"] or None)
        with ui.row().classes("w-full gap-3 items-center flex-wrap"):
            sel = (
                ui.select(tv.accounts, value=tv.selected, multiple=True, label="Comptes Hyperliquid")
                .props("outlined dense use-chips")
                .classes("min-w-[280px]")
            )
            per = (
                ui.select(PERIODS, value=STATE["period"], label="Période")
                .props("outlined dense")
                .classes("w-40")
            )
            sel.on_value_change(lambda e: (STATE.update(accounts=list(e.value or [])), refresh()))
            per.on_value_change(lambda e: (STATE.update(period=e.value), refresh()))
        if not tv.selected:
            ui.label("Sélectionnez au moins un compte.").classes("wc-muted")
        elif not tv.n_trades:
            empty_state("Aucun trade sur cette période. Les fills sont importés à chaque synchronisation.")
        else:
            with ui.column().classes("wc-card w-full gap-2"):
                _stats_row(tv.stats, m, big=True)
                if tv.stats["n_incomplete"]:
                    ui.label(
                        f"{tv.stats['n_incomplete']} trade(s) incomplet(s) inclus : ouverts avant le début de l'historique disponible."
                    ).classes("wc-muted text-xs")
            for coin, data in tv.by_coin.items():
                trades = data["trades"]
                opens = [t for t in trades if t["close_time"] is None]
                closed = [t for t in trades if t["close_time"] is not None]
                st = data["stats"]
                with ui.column().classes("wc-card w-full gap-2"):
                    with ui.row().classes("w-full items-center justify-between gap-2 flex-wrap"):
                        with ui.row().classes("items-center gap-2"):
                            avatar(coin)
                            ui.label(coin).classes("wc-section-title")
                            ui.label(
                                f"{st['n']} clos · winrate {fmt.pct(st['wr'], 0, False)} · PF {fmt.number(st['pf'])}"
                            ).classes("wc-muted text-sm")
                        ui.label(m(st["net"], True)).classes(f"font-semibold wc-num {sign_class(st['net'])}")
                    _trade_table(opens + closed[:VISIBLE], m, tv.live)
                    rest = closed[VISIBLE:]
                    if rest:
                        with ui.expansion(f"{len(rest)} trade(s) plus ancien(s)").classes("w-full text-sm"):
                            _trade_table(rest[:300], m, tv.live)
    else:
        alert("Aucun compte Hyperliquid suivi : ajoutez-en un dans Wallets pour importer vos trades.", "info")
    _manual_section(m, refresh)
