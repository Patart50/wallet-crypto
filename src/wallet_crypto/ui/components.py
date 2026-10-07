"""Briques d'interface réutilisées par toutes les pages."""

from __future__ import annotations

import hashlib
import html
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from nicegui import ui

from .. import fmt
from ..money import D
from .context import ctx
from .theme import SERIES


class Money:
    """Affichage des montants dans la devise choisie (dollar, ou euro au cours de la dernière sync)."""

    def __init__(self, currency: str, rate: Decimal | None):
        self.currency = currency if (currency == "USD" or rate) else "USD"
        self.rate = rate

    def __call__(self, x: Decimal | None, signed: bool = False) -> str:
        return fmt.money(x, self.currency, signed, self.rate)

    def conv(self, x: Decimal | None) -> float:
        """Valeur pour les graphiques (seul endroit où l'on passe en flottant)."""
        if x is None:
            return 0.0
        return float(x * self.rate) if self.currency == "EUR" and self.rate else float(x)

    @property
    def symbol(self) -> str:
        return "€" if self.currency == "EUR" else "$"


def money_fmt() -> Money:
    c = ctx()
    st = c.settings
    rate = c.prices.eur_per_usd()
    if rate is None:
        from ..db import store

        with c.db.session() as s:
            r = store.kv_get(s, "eur_per_usd")
        rate = D(r) if r else None
    return Money(st.currency, rate)


def theme_name() -> str:
    return ctx().settings.theme


def sign_class(x: Decimal | None) -> str:
    if x is None or x == 0:
        return "wc-muted"
    return "wc-pos" if x > 0 else "wc-neg"


def avatar(symbol: str, size: int = 34) -> None:
    sym = (symbol or "?").upper().replace("_STAKED", "").replace("_PENDING", "").replace("_SPOT", "")
    if sym.startswith("HLP"):
        sym = "HLP"
    pal = SERIES["dark"]
    color = pal[int(hashlib.sha1(sym.encode()).hexdigest(), 16) % len(pal)]
    ui.html(
        f'<span class="wc-avatar" style="background:{color};width:{size}px;height:{size}px" aria-hidden="true">{sym[:4]}</span>'
    )


def kpi(
    label: str, value: str, sub: str | None = None, sub_class: str = "wc-muted", dot: str | None = None
) -> None:
    # self-stretch : toutes les cases d'une rangée ont la même hauteur, sous-ligne ou non
    with ui.column().classes("wc-card-2 gap-1 min-w-[150px] flex-1 self-stretch justify-start"):
        with ui.row().classes("items-center gap-2"):
            if dot:
                ui.html(f'<span class="wc-dot" style="background:{dot}"></span>')
            ui.label(label).classes("wc-kpi-label")
        ui.label(value).classes("wc-kpi-value wc-num whitespace-nowrap")
        if sub:
            ui.label(sub).classes(f"text-xs wc-num {sub_class}")


def chip(text: str, tooltip: str | None = None) -> None:
    el = ui.html(f'<span class="wc-chip">{html.escape(str(text))}</span>')  # texte saisi possible
    if tooltip:
        el.tooltip(tooltip)


def page_title(title: str, subtitle: str | None = None) -> None:
    with ui.column().classes("gap-0"):
        ui.label(title).classes("wc-page-title").props('role="heading" aria-level="1"')
        if subtitle:
            ui.label(subtitle).classes("wc-muted text-sm")


def empty_state(text: str, action_label: str | None = None, action: Callable | None = None) -> None:
    with ui.column().classes("wc-card items-center w-full py-10 gap-3"):
        ui.icon("inbox", size="lg").classes("wc-muted")
        ui.label(text).classes("wc-muted text-center")
        if action_label and action:
            ui.button(action_label, on_click=action).props("unelevated color=primary no-caps")


def alert(text: str, kind: str = "warn") -> None:
    icon = {"warn": "warning_amber", "err": "error_outline", "info": "info_outline"}[kind]
    cls = {"warn": "wc-warn", "err": "wc-neg", "info": "wc-muted"}[kind]
    with ui.row().classes(f"wc-alert {kind} items-start gap-2 w-full no-wrap"):
        ui.icon(icon).classes(f"{cls} mt-[2px]")
        ui.label(text).classes("text-sm")


def confirm(
    title: str, text: str, on_yes: Callable, yes_label: str = "Supprimer", danger: bool = True
) -> None:
    with ui.dialog() as d, ui.card().classes("wc-card min-w-[320px]"):
        ui.label(title).classes("wc-section-title")
        ui.label(text).classes("wc-muted text-sm")
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            ui.button("Annuler", on_click=d.close).props("flat no-caps")

            def yes():
                d.close()
                on_yes()

            ui.button(yes_label, on_click=yes).props(
                f"unelevated no-caps color={'negative' if danger else 'primary'}"
            )
    d.open()


def dt_input(label: str, ms: int | None = None) -> ui.input:
    """Date et heure (sélecteur natif), dans le fuseau de l'utilisateur."""
    tz = ctx().config.tz
    when = datetime.fromtimestamp((ms or datetime.now().timestamp() * 1000) / 1000, tz)
    return (
        ui.input(label, value=when.strftime("%Y-%m-%dT%H:%M"))
        .props("type=datetime-local outlined dense")
        .classes("w-full")
    )


def parse_dt(value: str | None) -> int:
    tz = ctx().config.tz
    if not value:
        return int(datetime.now(tz).timestamp() * 1000)
    s = value.strip().replace(" ", "T")
    for f in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, f).replace(tzinfo=tz).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError("Date illisible.")


def dec_input(label: str, value: Decimal | str | None = None, hint: str | None = None) -> ui.input:
    """Champ numérique en texte : virgule ou point acceptés, valeur lue en décimal exact."""
    el = (
        ui.input(label, value="" if value is None else fmt.number(D(value), 12).rstrip("0").rstrip(","))
        .props("outlined dense inputmode=decimal")
        .classes("w-full")
    )
    if hint:
        el.props(f'hint="{hint}"')
    return el


def parse_dec(value: str | None, allow_empty: bool = False) -> Decimal | None:
    s = (value or "").strip().replace(" ", "").replace(" ", "").replace("\xa0", "")
    if not s:
        if allow_empty:
            return None
        raise ValueError("Valeur manquante.")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except ArithmeticError as exc:
        raise ValueError(f"Nombre illisible : {value}") from exc


def when(ms: int | None, with_time: bool = True) -> str:
    if not ms:
        return "—"
    tz = ctx().config.tz
    return datetime.fromtimestamp(ms / 1000, tz).strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def ago(ms: int | None) -> str:
    if not ms:
        return "jamais"
    s = max(0, datetime.now().timestamp() - ms / 1000)
    if s < 90:
        return "à l'instant"
    if s < 3600:
        return f"il y a {int(s // 60)} min"
    if s < 86400:
        return f"il y a {int(s // 3600)} h {int(s % 3600 // 60):02d}"
    return f"il y a {int(s // 86400)} j"


def asset_label(coin: str) -> str:
    """Nom lisible d'une ligne d'actif : « HYPE staké », « WCT à réclamer », « Vaults HLP »."""
    c = (coin or "").upper()
    if c == "HLP_VAULTS":
        return "Vaults HLP"
    if c.endswith("_STAKED"):
        return f"{c[:-7]} staké"
    if c.endswith("_PENDING"):
        return f"{c[:-8]} à réclamer"
    if c.endswith("_SPOT"):
        return f"{c[:-5]} spot"
    return c


def short_addr(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if len(a) > 14 else a
