"""Tableau de bord : patrimoine global, évolution, répartition, gains par poste."""

from __future__ import annotations

from nicegui import run, ui

from .. import fmt, services
from ..db import store
from ..history import HistoricalPrices
from ..services import POSTE_LABELS
from . import charts
from .components import (
    Money,
    ago,
    alert,
    asset_label,
    kpi,
    money_fmt,
    page_title,
    sign_class,
    theme_name,
    when,
)
from .context import ctx
from .theme import POSTE_ORDER, poste_color


def _compute_gains(key: str, start_ms: int, demo: bool) -> dict:
    c = ctx()
    cached = c.gains_cache.get(key)
    if cached is not None:
        return cached
    hp = HistoricalPrices(c.db, store.now_ms(), c.price_fn())
    res = services.gains_data(c.db, c.config, start_ms, hp)
    res["no_history"] = sorted(hp.missing)
    c.gains_cache[key] = res
    return res


def render(go_to) -> None:
    c = ctx()
    m = money_fmt()
    th = theme_name()
    dv = services.dashboard(c.db, c.config, c.price_fn())

    if not dv.has_wallets:
        page_title("Bienvenue", "Commencez par ajouter les adresses publiques de vos wallets.")
        with ui.column().classes("wc-hero w-full gap-3"):
            ui.label("Votre patrimoine crypto, chez vous.").classes("text-xl font-semibold")
            ui.label(
                "wallet-crypto lit les soldes de vos wallets Hyperliquid, EVM, Solana et Bitcoin à partir de leurs "
                "adresses publiques. Aucune clé privée, aucune phrase de récupération : jamais."
            ).classes("wc-muted")
            with ui.row().classes("gap-2"):
                ui.button("Ajouter un wallet", icon="add", on_click=lambda: go_to("wallets")).props(
                    "unelevated color=primary no-caps"
                )
                ui.button("Clé Alchemy", icon="key", on_click=lambda: go_to("settings")).props(
                    "outline no-caps"
                )
            ui.label(
                "Envie de voir avant ? Lancez la démonstration, avec des données fictives : wallet-crypto serve --demo."
            ).classes("wc-muted text-sm")
        return

    # ------------------------------------------------------------ héros : total et composition
    with ui.column().classes("wc-hero w-full gap-0").props('aria-label="Patrimoine global"'):
        with ui.row().classes("w-full items-start justify-between gap-4 flex-wrap"):
            with ui.column().classes("gap-1"):
                ui.label("Patrimoine global").classes("wc-kpi-label")
                ui.label(m(dv.total)).classes("wc-total")
                with ui.row().classes("gap-2 items-center flex-wrap mt-1"):
                    for dl in dv.deltas:
                        ui.html(
                            f'<span class="wc-chip"><span class="{sign_class(dl.amount)} wc-num">{m(dl.amount, True)} '
                            f"({fmt.pct(dl.pct)})</span>&nbsp;{dl.label}</span>"
                        ).tooltip("Évolution brute : inclut vos dépôts et retraits.")
                    if not dv.deltas:
                        ui.label("L'évolution apparaît après la deuxième synchronisation.").classes(
                            "wc-muted text-sm"
                        )
            with ui.column().classes("items-end gap-0"):
                ui.label(f"Synchronisé {ago(dv.last_sync_ms)}").classes("wc-muted text-sm")
                ui.label(f"{dv.n_wallets} wallet(s) suivi(s)").classes("wc-muted text-sm")
        parts = [(k, dv.postes.get(k) or 0) for k in POSTE_ORDER]
        total = sum((v for _, v in parts), 0) or 1
        segs = "".join(
            f'<span style="flex:{float(v / total):.6f} 1 0;background:{poste_color(th, k)}" title="{POSTE_LABELS[k]}"></span>'
            for k, v in parts
            if v > 0
        )
        ui.html(
            f'<div class="wc-compo" role="img" aria-label="Répartition du patrimoine par poste">{segs}</div>'
        ).classes("w-full")
        items = "".join(
            f'<div class="wc-legend-item"><span class="lbl"><span class="wc-dot" style="background:{poste_color(th, k)}"></span>'
            f'{POSTE_LABELS[k]}</span><span class="val">{m(v)}<span class="share">{fmt.pct(v / total * 100, 1, False) if dv.total else "—"}</span></span></div>'
            for k, v in parts
        )
        ui.html(f'<div class="wc-legend">{items}</div>').classes("w-full")

    if dv.unpriced:
        alert(f"{len(dv.unpriced)} actif(s) sans prix, non comptés : {', '.join(dv.unpriced)}.")
    if dv.duplicates:
        alert(
            f"Staking manuel exclu (déjà suivi automatiquement) : {', '.join(dv.duplicates)}. Supprimez la position manuelle si c'est le même staking."
        )
    if dv.n_errors:
        alert(
            f"{dv.n_errors} wallet(s) en erreur à la dernière synchronisation : voir l'onglet Wallets.", "err"
        )
    if not c.config.alchemy_key and not c.demo:
        alert(
            "Pas de clé Alchemy : les wallets EVM et Solana ne sont pas lus. Ajoutez la vôtre dans Réglages (gratuit).",
            "info",
        )

    # ------------------------------------------------------------ évolution + principaux actifs
    points = services.patrimoine_series(c.db, dv)
    with ui.row().classes("w-full gap-4 items-stretch flex-wrap lg:flex-nowrap"):
        with ui.column().classes("wc-card flex-[2] min-w-[300px] gap-1"):
            ui.label("Patrimoine par poste").classes("wc-section-title")
            ui.label("Valeur réelle des wallets à chaque synchronisation. Survolez pour le détail.").classes(
                "wc-muted text-sm"
            )
            if len(points) >= 2:
                ui.echart(charts.patrimoine_options(points, th, m)).classes("w-full h-80")
                with ui.expansion("Voir les données").classes("w-full text-sm"):
                    _patrimoine_table(points, m)
            else:
                ui.label("La courbe se dessine à partir de deux relevés.").classes(
                    "wc-muted text-sm py-16 self-center"
                )
        with ui.column().classes("wc-card flex-1 min-w-[280px] gap-1"):
            ui.label("Principaux actifs").classes("wc-section-title")
            with ui.element("table").classes("wc-table text-sm"):
                for a in dv.top_assets[:10]:
                    with ui.element("tr"):
                        with ui.element("td"):
                            ui.label(asset_label(a["coin"]))
                        with ui.element("td").classes("r"):
                            ui.label(m(a["val"]))
                        with ui.element("td").classes("r wc-muted"):
                            ui.label(fmt.pct(a["val"] / dv.total * 100, 1, False) if dv.total else "—")

    # ------------------------------------------------------------ gains
    opts = services.gain_start_options(c.db, c.config)
    state = {"key": services.default_gain_start(opts)}
    with ui.column().classes("wc-card w-full gap-2"):
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap"):
            with ui.column().classes("gap-0"):
                title = ui.label("Gains cumulés par poste").classes("wc-section-title")
                ui.label(
                    "Trading = réalisé + funding (positions ouvertes non incluses) · Staking = récompenses au cours du jour reçu · "
                    "Hold = réalisé + latent depuis le départ. Dépôts et retraits ne sont pas des gains."
                ).classes("wc-muted text-xs")
            sel = (
                ui.select({k: v[0] for k, v in opts.items()}, value=state["key"], label="Depuis")
                .props("outlined dense")
                .classes("min-w-[240px]")
            )
        totals = ui.row().classes("w-full gap-3 flex-wrap")
        chart_box = ui.column().classes("w-full")
        note = ui.label("").classes("wc-muted text-xs")

        async def load():
            key = sel.value
            if not key:
                return
            chart_box.clear()
            with chart_box:
                ui.skeleton().classes("w-full h-72")
            try:
                res = await run.io_bound(_compute_gains, key, opts[key][1], c.demo)
            except Exception as exc:  # réseau indisponible, etc.
                chart_box.clear()
                with chart_box:
                    alert(f"Gains indisponibles : {exc}", "err")
                return
            _render_gains(res, totals, chart_box, note, title, th, m, opts[key][0])

        sel.on_value_change(lambda _: ui.timer(0.01, load, once=True))
        ui.timer(0.05, load, once=True)


def _render_gains(res, totals, chart_box, note, title, th, m: Money, label: str) -> None:
    s = res["series"]
    total = s["total"][-1]
    title.text = f"Gains cumulés par poste : {m(total, True)}"
    totals.clear()
    with totals:
        for k in charts.GAIN_ORDER:
            v = s[k][-1]
            kpi(POSTE_LABELS[k], m(v, True), None, dot=poste_color(th, k))
    chart_box.clear()
    with chart_box:
        ui.echart(charts.gains_options(res, th, m)).classes("w-full h-80")
        with ui.expansion("Voir les données").classes("w-full text-sm"):
            rows = list(zip(res["grid"], *(s[k] for k in [*charts.GAIN_ORDER, "total"]), strict=True))
            step = max(1, len(rows) // 60)
            with ui.element("div").classes("wc-scroll"), ui.element("table").classes("wc-table"):
                with ui.element("tr"):
                    for h in ["Date", *(POSTE_LABELS[k] for k in charts.GAIN_ORDER), "Total"]:
                        _cell("th", h, "r" if h != "Date" else "")
                for r in rows[::-1][::step]:
                    with ui.element("tr"):
                        _cell("td", when(r[0], False))
                        for v in r[1:]:
                            _cell("td", m(v, True), "r")
    parts = [f"Depuis : {label.lower()}."]
    if res["excluded"]:
        parts.append(f"Exclus du hold faute d'historique de prix : {', '.join(res['excluded'])}.")
    if res.get("unpriced_rewards"):
        parts.append(f"{res['unpriced_rewards']} récompense(s) sans cours historique, non comptées.")
    note.text = " ".join(parts)


def _patrimoine_table(points, m: Money) -> None:
    step = max(1, len(points) // 60)
    with ui.element("div").classes("wc-scroll"), ui.element("table").classes("wc-table"):
        with ui.element("tr"):
            for h in ["Date", *(POSTE_LABELS[k] for k in POSTE_ORDER), "Total"]:
                _cell("th", h, "r" if h != "Date" else "")
        for t, p in points[::-1][::step]:
            with ui.element("tr"):
                _cell("td", when(t))
                for k in POSTE_ORDER:
                    _cell("td", m(p.get(k)), "r")
                _cell("td", m(sum((p.get(k) or 0 for k in POSTE_ORDER), 0)), "r")


def _cell(tag: str, text: str, cls: str = "") -> None:
    with ui.element(tag).classes(cls):
        ui.label(text)
