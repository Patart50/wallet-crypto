"""Serveur web (NiceGUI) : cadre commun, navigation, connexion, synchronisation en tâche de fond.

- Écoute sur 127.0.0.1 par défaut. Ailleurs, un mot de passe est obligatoire (wallet D-010) ;
  exception explicite ``--docker`` : le conteneur écoute sur 0.0.0.0 mais ``docker compose``
  ne publie le port que sur 127.0.0.1 de la machine hôte.
- Synchronisation automatique selon la fréquence des Réglages, prix courants rafraîchis toutes
  les 5 minutes (noms de paires uniquement). Rien de tout cela en mode démonstration.
- Toutes les ressources (Vue, Quasar, ECharts, icônes, polices) sont servies par l'application :
  aucun CDN.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from pathlib import Path

from fastapi.responses import RedirectResponse
from nicegui import app, run, ui

from .. import auth
from ..config import Config
from ..db import Database, store
from ..support import AUTHOR, AUTHOR_DISPLAY
from ..sync import run_sync
from . import about, dashboard, hold, settings_page, staking, trades, wallets
from . import context as context_mod
from .components import ago
from .context import AppContext, ctx
from .theme import ACCENT, CSS

log = logging.getLogger("wallet_crypto.ui")

STATIC = Path(__file__).parent / "static"
PRICE_REFRESH_S = 300
LOOP_S = 60

PAGES = [
    ("dashboard", "/", "Tableau de bord", "space_dashboard"),
    ("wallets", "/wallets", "Wallets", "account_balance_wallet"),
    ("staking", "/staking", "Staking", "savings"),
    ("hold", "/hold", "Hold", "inventory_2"),
    ("trades", "/trades", "Trades", "candlestick_chart"),
    ("settings", "/reglages", "Réglages", "tune"),
    ("about", "/a-propos", "À propos", "info"),
]
PATHS = {k: p for k, p, _, _ in PAGES}
RENDER = {
    "dashboard": dashboard.render,
    "wallets": wallets.render,
    "staking": staking.render,
    "hold": hold.render,
    "trades": trades.render,
    "about": about.render,
}


# ====================================================================== accès
THROTTLE = auth.LoginThrottle()


def _logged_in() -> bool:
    expected = ctx().auth_token()
    if expected is None:
        return True
    got = app.storage.user.get("auth")
    return isinstance(got, str) and hmac.compare_digest(got, expected)


class HostGuard:
    """Sans mot de passe, n'accepte que les requêtes adressées à la machine locale (D-035).

    Protège contre le « DNS rebinding » (une page web malveillante qui fait pointer son propre
    nom vers 127.0.0.1 pour lire l'interface) et contre un port publié par erreur sur le réseau.
    Couvre HTTP et WebSocket.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and ctx().password_hash() is None:
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
            if not auth.host_header_is_loopback(host):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = (
                    b"wallet-crypto : acces refuse. Sans mot de passe, l'interface ne repond qu'a "
                    b"http://127.0.0.1 ou http://localhost. Pour y acceder autrement, definissez "
                    b"WALLET_CRYPTO_PASSWORD."
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.inner(scope, receive, send)


# ====================================================================== synchronisation
async def sync_now(on_done=None) -> None:
    c = ctx()
    if c.demo:
        ui.notify("Mode démonstration : la synchronisation est désactivée.", type="info")
        return
    if c.syncing:
        ui.notify("Synchronisation déjà en cours.")
        return
    c.syncing = True
    ui.notify("Synchronisation lancée…")
    try:
        rep = await run.io_bound(run_sync, c.db, c.base_config)
    except Exception as exc:  # erreur inattendue : jamais silencieuse
        log.exception("Synchronisation : %s", exc)
        ui.notify(f"Synchronisation impossible : {exc}", type="negative", multi_line=True)
        return
    finally:
        c.syncing = False
    c.last_sync_report = rep
    c.bump()
    if rep.status == "busy":
        ui.notify("Une synchronisation est déjà en cours.")
    elif rep.status == "empty":
        ui.notify("Aucun wallet à synchroniser.")
    elif rep.n_errors:
        ui.notify(
            f"{rep.n_ok} wallet(s) lu(s), {rep.n_errors} en échec (anciens soldes conservés). Détail dans Wallets.",
            type="warning",
            multi_line=True,
        )
    else:
        ui.notify(f"{rep.n_ok} wallet(s) synchronisé(s).", type="positive")
    if on_done:
        on_done()


async def background_loop() -> None:
    """Prix courants toutes les 5 min ; synchronisation quand elle est due."""
    c = ctx()
    while True:
        if not c.demo:
            try:
                if time.time() - c.prices.loaded_at > PRICE_REFRESH_S:
                    await run.io_bound(c.prices.refresh, c.http())
            except Exception as exc:
                log.warning("Prix courants : %s", exc)
            if not c.syncing:
                c.syncing = True
                try:
                    rep = await run.io_bound(run_sync, c.db, c.base_config, None, True)
                    if rep.status not in ("not_due", "busy"):
                        c.last_sync_report = rep
                        c.bump()
                except Exception as exc:
                    log.exception("Synchronisation automatique : %s", exc)
                finally:
                    c.syncing = False
        await asyncio.sleep(LOOP_S)


# ====================================================================== cadre
def frame(key: str) -> None:
    c = ctx()
    st = c.settings
    theme = st.theme
    dark = ui.dark_mode(theme == "dark")
    ui.colors(
        primary=ACCENT[theme],
        positive="#1b7a4b" if theme == "light" else "#5cc48d",
        negative="#b42318" if theme == "light" else "#ff8a80",
    )
    ui.add_css(CSS, shared=False)
    ui.page_title(f"{dict((k, t) for k, _, t, _ in PAGES)[key]} · wallet-crypto")

    def apply_theme(value: str) -> None:
        dark.value = value == "dark"
        ui.colors(primary=ACCENT[value])

    with ui.header(elevated=False).classes("wc-header items-center px-4 py-2 gap-3 no-wrap"):
        ui.html('<a class="wc-skip" href="#contenu">Aller au contenu</a>')
        ui.button(icon="menu", on_click=lambda: drawer.toggle()).props(
            'flat dense round aria-label="Menu"'
        ).classes("lg:hidden")
        ui.html('<span class="wc-brand">wallet-crypto</span>')
        if c.demo:
            ui.html('<span class="wc-tag">démonstration</span>')
        ui.space()
        status = ui.label("").classes("wc-muted text-sm wc-hide-xs").props('aria-live="polite"')
        with (
            ui.button(on_click=lambda: sync_now(content.refresh))
            .props('outline no-caps dense aria-label="Synchroniser"')
            .classes("px-2") as sync_btn
        ):
            ui.icon("sync")
            ui.label("Synchroniser").classes("wc-hide-xs ml-2")
        if c.demo:
            sync_btn.disable()
            sync_btn.tooltip("Désactivé en démonstration : données fictives.")
        ui.button(
            icon="dark_mode" if theme == "light" else "light_mode",
            on_click=lambda: _toggle_theme(apply_theme),
        ).props(f'flat dense round aria-label="Passer en thème {"sombre" if theme == "light" else "clair"}"')
        if c.password_hash():
            ui.button(icon="logout", on_click=_logout).props('flat dense round aria-label="Se déconnecter"')

    with (
        ui.left_drawer(value=None, bordered=False)
        .classes("wc-drawer p-3 gap-1")
        .props("width=220 breakpoint=1024") as drawer
    ):
        with (
            ui.element("nav")
            .props('aria-label="Navigation principale"')
            .classes("flex flex-col gap-1 w-full")
        ):
            for k, path, label, icon in PAGES:
                with (
                    ui.link(target=path)
                    .classes(f"wc-nav-item {'active' if k == key else ''}")
                    .props('aria-current="page"' if k == key else "")
                ):
                    ui.icon(icon, size="20px")
                    ui.label(label)

    seen = {"v": c.version}

    def go_to(k: str) -> None:
        if k == key:
            c.bump()
            seen["v"] = c.version
            content.refresh()
        else:
            ui.navigate.to(PATHS[k])

    @ui.refreshable
    def content() -> None:
        if key == "settings":
            settings_page.render(go_to, apply_theme)
        else:
            RENDER[key](go_to)

    with ui.element("main").classes("wc-main w-full flex flex-col gap-4").props('id="contenu" tabindex="-1"'):
        content()
        with ui.row().classes("wc-footer w-full justify-between flex-wrap gap-2"):
            ui.html(
                f'<span>Créé par <a href="{AUTHOR["url"]}" target="_blank" rel="noopener">{AUTHOR_DISPLAY}</a> · '
                f'<a href="/a-propos#soutien">Soutenir le projet</a></span>'
            )
            ui.html("<span>Lecture seule · vos données restent sur votre machine</span>")

    def tick() -> None:
        with c.db.session() as s:
            last = store.last_sync(s)
        if c.syncing:
            status.text = "Synchronisation en cours…"
        else:
            status.text = f"Synchronisé {ago(last.started_ms if last else None)}"
        sync_btn.props(f"loading={'true' if c.syncing else 'false'}")
        if c.version != seen["v"]:
            seen["v"] = c.version
            content.refresh()

    tick()
    ui.timer(5.0, tick)


def _toggle_theme(apply_theme) -> None:
    from ..settings import save_setting

    c = ctx()
    new = "light" if c.settings.theme == "dark" else "dark"
    save_setting(c.db, "theme", new)
    ui.navigate.reload()


def _logout() -> None:
    app.storage.user["auth"] = False
    ui.navigate.to("/connexion")


def _page(key: str, path: str):
    @ui.page(path)
    def page():
        if not _logged_in():
            return RedirectResponse(f"/connexion?suite={path}", status_code=303)
        frame(key)
        return None

    return page


def register_pages() -> None:
    for k, path, _, _ in PAGES:
        _page(k, path)

    @ui.page("/connexion")
    async def login(suite: str = "/"):
        c = ctx()
        target = suite if suite in PATHS.values() else "/"
        if _logged_in():
            return RedirectResponse(target, status_code=303)
        theme = c.settings.theme
        ui.dark_mode(theme == "dark")
        ui.colors(primary=ACCENT[theme])
        ui.add_css(CSS, shared=False)
        ui.page_title("Connexion · wallet-crypto")

        async def submit() -> None:
            wait = THROTTLE.wait_s(time.time())
            if wait:
                ui.notify(f"Trop d'essais : réessayez dans {int(wait) + 1} s.", type="warning")
                return
            if auth.verify_password(pwd.value or "", c.password_hash()):
                THROTTLE.succeeded()
                app.storage.user["auth"] = c.auth_token()
                ui.navigate.to(target)
            else:
                THROTTLE.failed(time.time())
                await asyncio.sleep(1.0)  # freine les essais en rafale
                pwd.value = ""
                ui.notify("Mot de passe incorrect.", type="negative")

        with ui.column().classes("absolute-center wc-card gap-3 w-[min(380px,92vw)]"):
            ui.html('<span class="wc-brand">wallet-crypto</span>')
            ui.label("Saisissez le mot de passe de l'interface.").classes("wc-muted text-sm")
            pwd = (
                ui.input("Mot de passe", password=True)
                .props("outlined dense autofocus autocomplete=current-password")
                .classes("w-full")
            )
            pwd.on("keydown.enter", submit)
            ui.button("Se connecter", on_click=submit).props("unelevated color=primary no-caps").classes(
                "w-full"
            )


# ====================================================================== lancement
def serve(
    config: Config,
    host: str = "127.0.0.1",
    port: int = 8090,
    demo: bool = False,
    docker: bool = False,
    env_password: str | None = None,
) -> None:
    from ..settings import load_settings

    db = Database(config.db_path)
    db.init()
    env_hash = auth.hash_password(env_password) if env_password else None
    secret = auth.storage_secret(config.data_dir)
    c = AppContext(
        db=db,
        base_config=config,
        demo=demo,
        env_password_hash=env_hash,
        env_password_token=auth.session_token(secret, "env:" + env_password) if env_password else None,
        secret=secret,
        exposed=not auth.is_loopback(host) and not docker,
    )
    context_mod.CTX = c
    has_password = bool(env_hash or load_settings(db, config).password_hash)
    if not auth.is_loopback(host) and not has_password and not docker:
        raise SystemExit(
            f"Refusé : l'interface écouterait sur {host} sans mot de passe, et elle révèle tout votre patrimoine.\n"
            "Définissez WALLET_CRYPTO_PASSWORD (8 caractères minimum), ou restez sur 127.0.0.1."
        )
    if docker and not has_password:
        log.warning("Mode Docker sans mot de passe : le port doit rester publié sur 127.0.0.1 uniquement.")

    app.add_middleware(HostGuard)
    app.add_static_files("/wc-static", STATIC)
    register_pages()
    app.on_startup(lambda: asyncio.create_task(background_loop()))
    print(
        f"wallet-crypto : http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
        + (" (démonstration)" if demo else "")
    )
    ui.run(
        host=host,
        port=port,
        title="wallet-crypto",
        favicon=STATIC / "favicon.svg",
        language="fr",
        dark=None,
        reload=False,
        show=False,
        storage_secret=secret,
        uvicorn_logging_level="warning",
        reconnect_timeout=10,
    )
