"""À propos et limites : ce que fait l'outil, où vont les données, ce qu'il ne sait pas faire,
auteur et soutien (wallet D-012). Les QR codes sont générés sur le serveur (``segno``) : aucun
appel réseau."""

from __future__ import annotations

import io
from html import escape

import segno
from nicegui import ui

from .. import __version__
from ..support import AUTHOR, AUTHOR_DISPLAY, DONATION_ADDRESSES, REPO_URL, SPONSORS_URL
from .components import page_title

LIMITS = [
    "Le patrimoine n'est connu qu'à partir de votre première synchronisation : le passé n'est pas reconstitué.",
    "L'évolution du patrimoine est brute : elle inclut vos dépôts et retraits.",
    "Hyperliquid ne fournit que les 10 000 derniers fills : un trade ouvert avant est marqué incomplet. "
    "wallet-crypto archive ensuite tout localement.",
    "Les tokens sans prix chez Alchemy sont ignorés (presque toujours du spam d'airdrop), comme la poussière de moins de 1 $.",
    "Bitcoin : une adresse par ligne, pas de clé étendue (xpub).",
    "Prix historiques : clôture journalière (jour UTC). Un actif sans historique est exclu du graphique des gains et signalé.",
    "Staking manuel en mode APR : le montant est estimé à partir du taux saisi, pas relevé sur la plateforme.",
    "Pas encore de connexion aux plateformes centralisées (Binance, Coinbase…) : leurs trades se saisissent à la main.",
    "Aucun calcul fiscal : pour la déclaration française, utilisez pmpa-crypto.",
]


def qr_svg(data: str) -> str:
    buf = io.BytesIO()
    segno.make(data, error="m").save(
        buf, kind="svg", scale=4, border=2, dark="#000000", light="#ffffff", xmldecl=False, svgns=True
    )
    return buf.getvalue().decode()


def _para(text: str) -> None:
    ui.html(f"<p>{text}</p>")


def render(go_to) -> None:
    page_title("À propos et limites", f"wallet-crypto {__version__}, logiciel libre sous licence AGPL-3.0.")

    with ui.column().classes("wc-card w-full gap-1 wc-prose"):
        ui.label("Ce que fait wallet-crypto").classes("wc-section-title")
        _para(
            "Il rassemble sur un écran les soldes réels de vos wallets Hyperliquid, EVM, Solana et Bitcoin, "
            "votre staking avec son rendement réel, le prix moyen d'achat de votre hold et vos trades Hyperliquid, "
            "nets de frais et de funding."
        )
        _para(
            "Il fonctionne en <b>lecture seule</b> : il ne demande que des adresses publiques. Une clé privée ou une "
            "phrase de récupération collée par erreur est refusée."
        )

    with ui.column().classes("wc-card w-full gap-1 wc-prose"):
        ui.label("Où vont vos données").classes("wc-section-title")
        _para(
            "Tout est enregistré sur votre machine, dans le dossier <span class='wc-mono'>data/</span>. Aucune "
            "télémétrie, aucun compte."
        )
        _para(
            "Pour lire les soldes, vos adresses sont envoyées aux services qui les fournissent : Hyperliquid, "
            "Alchemy (avec votre clé) et mempool.space. Les prix viennent de Binance et de Hyperliquid : seuls des "
            "noms de paires sont envoyés."
        )

    with ui.column().classes("wc-card w-full gap-1 wc-prose"):
        ui.label("Limites connues").classes("wc-section-title")
        with ui.element("ul").classes("pl-5 list-disc"):
            for item in LIMITS:
                with ui.element("li").classes("mb-1"):
                    ui.label(item)

    with ui.column().classes("wc-card w-full gap-3").props('id="soutien"'):
        ui.label("Auteur et soutien").classes("wc-section-title")
        ui.html(
            f'<p class="wc-prose">Créé par <a class="wc-link" href="{AUTHOR["url"]}" target="_blank" rel="noopener">'
            f"{escape(AUTHOR_DISPLAY)}</a>. wallet-crypto est gratuit et open source. S'il vous est utile, vous pouvez "
            f'soutenir son développement sur <a class="wc-link" href="{SPONSORS_URL}" target="_blank" rel="noopener">'
            "GitHub Sponsors</a> ou par un don en crypto.</p>"
        )
        with ui.row().classes("w-full gap-4 flex-wrap"):
            for a in DONATION_ADDRESSES:
                with ui.column().classes("wc-card-2 gap-2 flex-1 min-w-[260px] items-start"):
                    ui.label(a.label).classes("font-semibold")
                    ui.label(a.networks).classes("wc-muted text-sm")
                    ui.html(qr_svg(a.qr)).classes("wc-qr").props(
                        f'role="img" aria-label="QR code de l\'adresse {a.label}"'
                    )
                    with ui.row().classes("items-center gap-1 no-wrap w-full"):
                        ui.label(a.address).classes("wc-mono break-all")
                        ui.button(
                            icon="content_copy",
                            on_click=lambda addr=a.address: (
                                ui.clipboard.write(addr),
                                ui.notify("Adresse copiée"),
                            ),
                        ).props(f'flat dense round aria-label="Copier l\'adresse {a.label}"')
                    ui.label(a.warning).classes("wc-warn text-sm")
        ui.html(
            f'<p class="wc-muted text-sm">Code source : <a class="wc-link" href="{REPO_URL}" target="_blank" rel="noopener">'
            f"{REPO_URL.removeprefix('https://')}</a>. Projets frères : pmpa-crypto, dca-crypto, renfort-crypto, carnet-crypto.</p>"
        )

    with ui.column().classes("wc-card w-full gap-1 wc-prose"):
        ui.label("Avertissement").classes("wc-section-title")
        _para(
            "wallet-crypto est un outil de suivi, fourni sans garantie. Il ne constitue pas un conseil en "
            "investissement. Vérifiez les montants importants sur vos plateformes."
        )
