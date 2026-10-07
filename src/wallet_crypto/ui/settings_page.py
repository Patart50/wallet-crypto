"""Réglages : clé Alchemy (avec le guide), affichage, synchronisation, accès, sauvegarde."""

from __future__ import annotations

import inspect

from nicegui import ui

from .. import auth, backup, services
from ..log import add_secret
from ..security import mask_secret
from ..settings import save_setting
from .components import alert, confirm, page_title, when
from .context import ctx

ALCHEMY_STEPS = [
    (
        "Créez un compte gratuit",
        'Sur <a class="wc-link" href="https://dashboard.alchemy.com" target="_blank" rel="noopener">dashboard.alchemy.com</a>, forfait gratuit.',
    ),
    ("Créez une app", "Bouton « Create new app », nom au choix (par exemple wallet-crypto)."),
    (
        "Activez les réseaux",
        "Ethereum, Arbitrum, Base, BNB Smart Chain, Polygon, Optimism et Solana (mainnet).",
    ),
    ("Copiez la clé", "Dans l'app, copiez l'« API Key »."),
    ("Collez-la ici", "Ou dans le fichier .env (ALCHEMY_API_KEY=…), qui reste prioritaire."),
]


def _section(title: str, subtitle: str | None = None):
    col = ui.column().classes("wc-card w-full gap-3")
    with col:
        ui.label(title).classes("wc-section-title")
        if subtitle:
            ui.label(subtitle).classes("wc-muted text-sm")
    return col


def render(go_to, apply_theme) -> None:
    c = ctx()
    st = c.settings

    def refresh():
        c.bump()
        go_to("settings")

    page_title("Réglages")

    # ------------------------------------------------------------ Alchemy
    with _section(
        "Clé Alchemy",
        "Nécessaire pour les wallets EVM, Solana et le staking WCT. Gratuite, personnelle, en lecture seule : elle ne donne accès à aucun fonds.",
    ):
        if st.alchemy_from_env:
            ui.label(f"Clé définie dans le fichier .env : {mask_secret(st.alchemy_key)}").classes("wc-mono")
            ui.label("Pour la changer, modifiez .env puis redémarrez l'application.").classes(
                "wc-muted text-sm"
            )
        else:
            if st.alchemy_key:
                ui.label(f"Clé enregistrée : {mask_secret(st.alchemy_key)}").classes("wc-mono")
            key = (
                ui.input("Nouvelle clé", password=True, password_toggle_button=True)
                .props("outlined dense autocomplete=off")
                .classes("w-full max-w-[520px]")
            )

            def save_key():
                v = (key.value or "").strip()
                if len(v) < 10 or " " in v:
                    ui.notify("Clé invalide : copiez l'« API Key » de votre app Alchemy.", type="negative")
                    return
                save_setting(c.db, "alchemy_key", v)
                add_secret(v)
                ui.notify("Clé enregistrée. Lancez une synchronisation.", type="positive")
                refresh()

            def remove_key():
                save_setting(c.db, "alchemy_key", "")
                refresh()

            with ui.row().classes("gap-2"):
                ui.button("Enregistrer", on_click=save_key).props("unelevated color=primary no-caps")
                if st.alchemy_key:
                    ui.button("Retirer la clé", on_click=remove_key).props("flat no-caps color=negative")
        with ui.expansion("Comment obtenir ma clé ?", value=not st.alchemy_key).classes("w-full"):
            with ui.column().classes("gap-2"):
                for i, (t, txt) in enumerate(ALCHEMY_STEPS, 1):
                    with ui.row().classes("items-start gap-3 no-wrap"):
                        ui.label(str(i)).classes("wc-avatar").style(
                            "background: var(--wc-accent); width:26px; height:26px"
                        )
                        with ui.column().classes("gap-0"):
                            ui.label(t).classes("font-semibold")
                            ui.html(f'<span class="wc-muted text-sm">{txt}</span>')
                ui.label(
                    "Si la clé fuit : régénérez-la dans le tableau de bord Alchemy et remplacez-la ici. "
                    "wallet-crypto ne l'écrit jamais en clair dans ses journaux."
                ).classes("wc-muted text-sm")

    # ------------------------------------------------------------ Affichage
    with _section("Affichage"):
        with ui.row().classes("gap-6 items-center flex-wrap"):
            cur = ui.toggle({"USD": "Dollar ($)", "EUR": "Euro (€)"}, value=st.currency).props("no-caps")
            cur.on_value_change(lambda e: (save_setting(c.db, "currency", e.value), refresh()))
            th = ui.toggle({"dark": "Sombre", "light": "Clair"}, value=st.theme).props("no-caps")

            def set_theme(e):
                save_setting(c.db, "theme", e.value)
                apply_theme(e.value)
                refresh()

            th.on_value_change(set_theme)
        ui.label(
            "Les montants sont calculés en dollars ; l'euro est converti au cours EUR/USDT de Binance."
        ).classes("wc-muted text-sm")

    # ------------------------------------------------------------ Synchronisation
    with _section(
        "Synchronisation",
        "Automatique tant que l'application tourne. Une source en échec garde ses anciens soldes.",
    ):
        hours = (
            ui.number("Intervalle (heures)", value=st.sync_hours, min=1, max=48, step=1, format="%.0f")
            .props("outlined dense")
            .classes("w-48")
        )
        hours.on(
            "blur",
            lambda: (
                save_setting(c.db, "sync_hours", float(hours.value or 6)),
                ui.notify("Intervalle enregistré"),
            ),
        )
        rep = c.last_sync_report
        if rep is not None:
            ui.label(
                f"Dernière synchronisation lancée ici : {rep.n_ok} wallet(s) lu(s), {rep.n_errors} erreur(s)."
            ).classes("wc-muted text-sm")

    # ------------------------------------------------------------ Accès
    with _section(
        "Accès",
        "Mot de passe de l'interface. Obligatoire si l'application est accessible depuis d'autres appareils : la page révèle tout votre patrimoine.",
    ):
        if c.env_password_hash:
            ui.label("Mot de passe défini par la variable WALLET_CRYPTO_PASSWORD.").classes(
                "wc-muted text-sm"
            )
        else:
            ui.label(
                "Mot de passe défini." if st.password_hash else "Aucun mot de passe (accès local uniquement)."
            ).classes("text-sm")
            p1 = (
                ui.input("Nouveau mot de passe", password=True)
                .props("outlined dense autocomplete=new-password")
                .classes("w-full max-w-[360px]")
            )
            p2 = (
                ui.input("Confirmation", password=True)
                .props("outlined dense autocomplete=new-password")
                .classes("w-full max-w-[360px]")
            )

            def set_pwd():
                if p1.value != p2.value:
                    ui.notify("Les deux saisies diffèrent.", type="negative")
                    return
                try:
                    save_setting(c.db, "password_hash", auth.hash_password(p1.value or ""))
                except ValueError as exc:
                    ui.notify(str(exc), type="negative")
                    return
                ui.notify("Mot de passe enregistré.", type="positive")
                refresh()

            with ui.row().classes("gap-2"):
                ui.button("Enregistrer", on_click=set_pwd).props("unelevated color=primary no-caps")
                if st.password_hash:
                    ui.button(
                        "Supprimer le mot de passe",
                        on_click=lambda: (save_setting(c.db, "password_hash", None), refresh()),
                    ).props("flat no-caps color=negative")

    # ------------------------------------------------------------ Historique
    with _section(
        "Historique du patrimoine",
        "Une adresse ajoutée par erreur (un contrat, l'adresse de quelqu'un d'autre) reste dans les relevés "
        "passés et les courbes même après sa suppression. Le nettoyage retire, pour chaque wallet supprimé, "
        "sa part de chaque relevé et son historique importé. Les wallets suivis, même en pause, ne sont pas touchés.",
    ):

        def do_purge():
            def yes():
                try:
                    keep = backup.export_bytes(c.db)
                    backups = c.base_config.data_dir / "backups"
                    backups.mkdir(exist_ok=True)
                    (
                        backups / f"avant-nettoyage-{__import__('time').strftime('%Y%m%d-%H%M%S')}.db"
                    ).write_bytes(keep)
                except backup.BackupError:
                    pass
                n = services.purge_history(c.db)
                if not any(n.values()):
                    ui.notify("Rien à nettoyer : l'historique ne contient aucun wallet supprimé.")
                else:
                    ui.notify(
                        f"Nettoyé : {n['snapshots']} relevé(s) corrigé(s), {n['fills']} fill(s), "
                        f"{n['funding']} funding, {n['stake_events']} mouvement(s) de staking retirés. "
                        "Copie de la base gardée dans data/backups.",
                        type="positive",
                        multi_line=True,
                    )
                refresh()

            confirm(
                "Nettoyer l'historique ?",
                "Les wallets supprimés sont retirés des relevés passés et de l'historique importé. "
                "Une copie de la base est gardée dans data/backups avant l'opération.",
                yes,
                yes_label="Nettoyer",
            )

        ui.button("Nettoyer l'historique", icon="cleaning_services", on_click=do_purge).props(
            "outline no-caps"
        )

    # ------------------------------------------------------------ Données
    with _section(
        "Vos données",
        f"Tout est dans {c.base_config.data_dir}. Sauvegarder = copier ce dossier, ou exporter la base ici.",
    ):

        def do_export():
            try:
                data = backup.export_bytes(c.db)
            except backup.BackupError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.download.content(
                data,
                f"wallet-crypto-{when(None) if False else ''}{__import__('time').strftime('%Y%m%d-%H%M')}.db",
            )

        ui.button("Exporter la base", icon="download", on_click=do_export).props("outline no-caps")

        async def on_upload(e):
            f = getattr(e, "file", None)
            if f is not None:
                data = f.read()
                if inspect.isawaitable(data):
                    data = await data
            else:
                data = e.content.read()
            try:
                keep = backup.import_bytes(c.db, data)
            except backup.BackupError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Base importée. L'ancienne est gardée dans {keep.name}.", type="positive")
            refresh()

        ui.label(
            "Importer une sauvegarde remplace la base actuelle (une copie est gardée dans data/backups)."
        ).classes("wc-muted text-sm")
        ui.upload(
            label="Importer une sauvegarde (.db)",
            auto_upload=True,
            on_upload=on_upload,
            max_file_size=200_000_000,
        ).props('accept=".db" flat').classes("wc-upload")
    if c.demo:
        alert("Mode démonstration : données fictives, aucune API n'est contactée.", "info")
