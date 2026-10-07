"""Thème de l'interface : sombre par défaut, clair disponible (wallet D-009, D-023).

Identité commune au programme (commun-crypto ``theme.css``) : papier et encre marine, Public
Sans pour l'interface, Source Serif 4 pour le montant du patrimoine, chiffres tabulaires.
Polices embarquées dans le paquet (``static/fonts``, licence OFL) : aucun CDN.

Couleurs des séries validées avec le validateur de palette du programme sur la surface de
chaque thème (#171f2e en sombre, #ffffff en clair) : bande de luminance, chroma, séparation
pour les daltonismes (ΔE ≥ 8,4 entre voisins), contraste ≥ 3:1 en sombre. En clair, trois
séries passent sous 3:1 : les valeurs sont donc toujours écrites à côté des graphiques, et
chaque graphique a sa vue en tableau.
"""

from __future__ import annotations

SERIES = {
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
}
POSTE_ORDER = ["stake", "hold", "auto", "manuel", "autres"]

CHART = {
    "dark": {
        "text": "#e5e9f0",
        "muted": "#9aa4b5",
        "grid": "#2a3446",
        "tooltip_bg": "#1c2536",
        "surface": "#171f2e",
    },
    "light": {
        "text": "#172033",
        "muted": "#5a6478",
        "grid": "#d8dde5",
        "tooltip_bg": "#ffffff",
        "surface": "#ffffff",
    },
}
# Couleur Quasar « primary » (boutons pleins, interrupteurs). En sombre, l'accent clair #8ea6ff
# des liens donnerait un texte blanc à 2,3:1 : #4f6ae0 donne 4,7:1 (AA) et 3,5:1 sur la surface.
ACCENT = {"dark": "#4f6ae0", "light": "#2541b2"}
FONT_UI = "'Public Sans', system-ui, sans-serif"


def poste_color(theme: str, poste: str) -> str:
    return SERIES[theme][POSTE_ORDER.index(poste)]


def series_color(theme: str, i: int) -> str:
    pal = SERIES[theme]
    return pal[i % len(pal)]


CSS = r"""
@font-face {
  font-family: 'Public Sans'; font-style: normal; font-display: swap; font-weight: 100 900;
  src: url('/wc-static/fonts/public-sans-latin-wght-normal.woff2') format('woff2-variations');
}
@font-face {
  font-family: 'Source Serif 4'; font-style: normal; font-display: swap; font-weight: 200 900;
  src: url('/wc-static/fonts/source-serif-4-latin-wght-normal.woff2') format('woff2-variations');
}
:root {
  --wc-font: 'Public Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --wc-font-doc: 'Source Serif 4', Georgia, serif;
  --wc-radius: 6px; --wc-radius-lg: 10px;
}
.body--light {
  --wc-bg: #f2f4f7; --wc-surface: #ffffff; --wc-surface-2: #f7f8fa; --wc-border: #d8dde5; --wc-border-strong: #b9c1ce;
  --wc-text: #172033; --wc-muted: #5a6478; --wc-accent: #2541b2; --wc-accent-soft: #e8ecfb; --wc-on-accent: #ffffff;
  --wc-pos: #1b7a4b; --wc-neg: #b42318; --wc-warn: #8a5300; --wc-warn-bg: #fff4de;
}
.body--dark {
  --wc-bg: #0f1521; --wc-surface: #171f2e; --wc-surface-2: #1c2536; --wc-border: #2a3446; --wc-border-strong: #3b475d;
  --wc-text: #e5e9f0; --wc-muted: #9aa4b5; --wc-accent: #8ea6ff; --wc-accent-soft: #1f2a4a; --wc-on-accent: #0f1521;
  --wc-pos: #5cc48d; --wc-neg: #ff8a80; --wc-warn: #f2b45a; --wc-warn-bg: #2e2410;
}
body { background: var(--wc-bg) !important; color: var(--wc-text); font-family: var(--wc-font); font-size: 15px; }
.q-field, .q-btn, .q-item, .q-tab, .q-toggle, .q-menu, .q-tooltip, .q-notification { font-family: var(--wc-font); }
.nicegui-content { padding: 0 !important; }
.wc-num { font-variant-numeric: tabular-nums; }
.wc-muted { color: var(--wc-muted); }
.wc-pos { color: var(--wc-pos); }
.wc-neg { color: var(--wc-neg); }
.wc-warn { color: var(--wc-warn); }

/* Cartes : une bordure, pas d'ombre ; deux rayons selon la hiérarchie */
.wc-card { background: var(--wc-surface); border: 1px solid var(--wc-border); border-radius: var(--wc-radius-lg); padding: 18px 20px; }
.wc-card-2 { background: var(--wc-surface-2); border: 1px solid var(--wc-border); border-radius: var(--wc-radius); padding: 10px 12px; }

/* Cadre */
.wc-header { background: var(--wc-surface) !important; border-bottom: 1px solid var(--wc-border); color: var(--wc-text) !important; }
.wc-brand { white-space: nowrap; font-weight: 700; letter-spacing: -0.01em; font-size: 1.05rem; }
.wc-brand small { font-weight: 400; color: var(--wc-muted); margin-left: 6px; font-size: .8rem; }
.wc-drawer { background: var(--wc-surface) !important; border-right: 1px solid var(--wc-border); }
.wc-nav-item {
  display: flex; align-items: center; gap: 10px; border-radius: var(--wc-radius); color: var(--wc-muted);
  padding: 8px 12px; cursor: pointer; font-weight: 500; text-decoration: none; border-left: 3px solid transparent;
}
.wc-nav-item:hover { background: var(--wc-surface-2); color: var(--wc-text); }
.wc-nav-item.active { color: var(--wc-text); border-left-color: var(--wc-accent); background: var(--wc-accent-soft); }
.wc-main { max-width: 1240px; margin: 0 auto; padding: 24px 24px 40px; }

/* Héros : le montant du patrimoine, seul élément appuyé de l'interface */
.wc-hero { background: var(--wc-surface); border: 1px solid var(--wc-border); border-radius: var(--wc-radius-lg); padding: 24px 26px 20px; }
.wc-total {
  font-family: var(--wc-font-doc); font-variant-numeric: tabular-nums lining-nums;
  font-size: clamp(2.4rem, 5.5vw, 3.6rem); font-weight: 600; letter-spacing: -0.015em; line-height: 1.02;
}
.wc-compo { display: flex; gap: 2px; height: 14px; width: 100%; margin: 18px 0 10px; }
.wc-compo > span { height: 100%; border-radius: 2px; min-width: 3px; }
.wc-compo > span:first-child { border-radius: 4px 2px 2px 4px; }
.wc-compo > span:last-child { border-radius: 2px 4px 4px 2px; }
.wc-legend { display: flex; flex-wrap: wrap; gap: 6px 22px; }
.wc-legend-item { display: flex; flex-direction: column; gap: 1px; min-width: 120px; }
.wc-legend-item .lbl { display: flex; align-items: center; gap: 7px; color: var(--wc-muted); font-size: .82rem; }
.wc-legend-item .val { font-weight: 600; font-variant-numeric: tabular-nums; }
.wc-legend-item .share { color: var(--wc-muted); font-size: .8rem; font-variant-numeric: tabular-nums; font-weight: 400; margin-left: 6px; }

.wc-kpi-label { font-size: .82rem; color: var(--wc-muted); }
.wc-kpi-value { font-size: 1.3rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.wc-chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px; font-size: .8rem;
  background: var(--wc-surface-2); border: 1px solid var(--wc-border); color: var(--wc-muted);
}
.wc-tag { display: inline-block; padding: 0 7px; border-radius: 4px; font-size: .74rem; font-weight: 600; background: var(--wc-accent-soft); color: var(--wc-accent); }
.wc-dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; flex-shrink: 0; }
.wc-avatar {
  width: 34px; height: 34px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: .72rem; color: #fff; flex-shrink: 0; letter-spacing: -0.02em;
}
.wc-section-title { font-size: 1.05rem; font-weight: 650; }
.wc-page-title { font-size: 1.55rem; font-weight: 700; letter-spacing: -0.015em; }
.wc-table { width: 100%; border-collapse: collapse; }
.wc-table th { text-align: left; font-weight: 500; color: var(--wc-muted); font-size: .8rem; padding: 6px 8px; border-bottom: 1px solid var(--wc-border-strong); }
.wc-table td { padding: 7px 8px; border-bottom: 1px solid var(--wc-border); font-variant-numeric: tabular-nums; }
.wc-table tr:last-child td { border-bottom: none; }
.wc-table td.r, .wc-table th.r { text-align: right; }
.wc-scroll { overflow-x: auto; width: 100%; }
.wc-alert { border-radius: var(--wc-radius); padding: 9px 13px; border: 1px solid var(--wc-border); background: var(--wc-surface); }
.wc-alert.warn { border-color: var(--wc-warn); background: var(--wc-warn-bg); }
.wc-alert.err { border-color: var(--wc-neg); }
.wc-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .86em; }
.wc-footer { color: var(--wc-muted); font-size: .84rem; border-top: 1px solid var(--wc-border); padding-top: 14px; margin-top: 8px; }
.wc-footer a, .wc-link { color: var(--wc-accent); text-decoration: none; }
.wc-footer a:hover, .wc-link:hover { text-decoration: underline; }
.wc-prose { max-width: 70ch; line-height: 1.6; }
.wc-prose p { margin: 0 0 .7em; }
.wc-qr svg { width: 164px; height: 164px; background: #fff; border-radius: var(--wc-radius); padding: 6px; }
.wc-upload { max-width: 420px; }
.wc-upload .q-uploader__list { display: none; }
.wc-upload .q-uploader__header { background: var(--wc-surface-2) !important; color: var(--wc-text) !important; border: 1px dashed var(--wc-border-strong); border-radius: var(--wc-radius); }
.wc-upload .q-uploader__subtitle { display: none; }
.q-field__label, .q-field__native, .q-field__input { color: var(--wc-text) !important; }
.body--dark .q-field--outlined .q-field__control:before { border-color: var(--wc-border-strong); }
/* Focus clavier toujours visible (Quasar le retire des boutons) ; pas sur les champs, déjà soulignés */
:focus-visible:not(.q-field__native):not(input):not(textarea) { outline: 2px solid var(--wc-accent) !important; outline-offset: 2px; }
.q-btn:focus-visible, .q-toggle:focus-visible .q-toggle__inner, .q-checkbox:focus-visible .q-checkbox__inner,
.q-expansion-item .q-item:focus-visible { box-shadow: 0 0 0 2px var(--wc-bg), 0 0 0 4px var(--wc-accent) !important; }
.wc-skip { position: absolute; left: -9999px; }
.wc-skip:focus { left: 12px; top: 8px; z-index: 9999; background: var(--wc-surface); padding: 8px 12px; border-radius: var(--wc-radius); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
@media (max-width: 600px) { .wc-hide-xs { display: none !important; } .wc-kpi-value { font-size: 1.08rem; } .wc-card-2 { padding: 8px 10px; } .wc-card { padding: 14px; } .wc-hero { padding: 18px; } .wc-main { padding: 16px 14px 32px; } }
"""
