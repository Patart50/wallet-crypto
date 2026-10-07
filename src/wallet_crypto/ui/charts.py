"""Options ECharts : patrimoine par poste (aire empilée) et gains cumulés (lignes).

Un seul axe par graphique, légende toujours présente, info-bulle au survol avec tous les
montants, marques fines, séparation de 1,5 px entre les aires empilées, couleurs fixes par poste
(jamais selon le rang). La répartition actuelle est une barre de composition en HTML (héros du
tableau de bord) : une barre empilée ne met côte à côte que des voisins, validés par la palette,
contrairement à un anneau à cinq parts."""

from __future__ import annotations

from ..services import POSTE_LABELS
from .components import Money
from .theme import CHART, FONT_UI, POSTE_ORDER, poste_color

GAIN_ORDER = ["stake", "hold", "auto", "manuel"]


def _fmt_js(m: Money) -> str:
    sym = m.symbol
    return (
        "v => { const a = Math.abs(v).toLocaleString('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2});"
        f" return (v < 0 ? '−' : '') + a + ' {sym}'; }}"
    )


def _tooltip(theme: str, m: Money, total: bool) -> dict:
    c = CHART[theme]
    total_js = (
        "rows.push('<div style=\"margin-top:4px;padding-top:4px;border-top:1px solid "
        + c["grid"]
        + "\"><b>Total : ' + fmt(tot) + '</b></div>');"
        if total
        else ""
    )
    return {
        "trigger": "axis",
        "axisPointer": {"type": "line", "lineStyle": {"color": c["muted"], "width": 1}},
        "backgroundColor": c["tooltip_bg"],
        "borderColor": c["grid"],
        "textStyle": {"color": c["text"], "fontSize": 12},
        ":formatter": (
            "ps => { const fmt = " + _fmt_js(m) + "; let tot = 0;"
            " const d = new Date(ps[0].value[0]);"
            " const rows = ['<b>' + d.toLocaleString('fr-FR', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'}) + '</b>'];"
            " ps.forEach(p => { if (p.seriesName === 'Total') { return; } tot += p.value[1];"
            " rows.push(p.marker + p.seriesName + ' : <b>' + fmt(p.value[1]) + '</b>'); });"
            + total_js
            + " return rows.join('<br>'); }"
        ),
    }


def _base(theme: str, m: Money) -> dict:
    c = CHART[theme]
    return {
        "backgroundColor": "transparent",
        "animation": False,
        "textStyle": {"fontFamily": FONT_UI},
        "grid": {"left": 8, "right": 12, "top": 44, "bottom": 40, "containLabel": True},
        "legend": {
            "type": "scroll",
            "top": 0,
            "left": 0,
            "right": 0,
            "pageIconColor": c["muted"],
            "pageTextStyle": {"color": c["muted"]},
            "icon": "roundRect",
            "itemWidth": 12,
            "itemHeight": 12,
            "textStyle": {"color": c["muted"]},
            "itemGap": 16,
        },
        "xAxis": {
            "type": "time",
            "axisLine": {"lineStyle": {"color": c["grid"]}},
            "axisTick": {"show": False},
            "splitLine": {"show": False},
            "axisLabel": {
                "color": c["muted"],
                "hideOverlap": True,
                ":formatter": "v => new Date(v).toLocaleDateString('fr-FR', {day:'2-digit', month:'short'})",
            },
        },
        "yAxis": {
            "type": "value",
            "splitLine": {"lineStyle": {"color": c["grid"]}},
            "axisLabel": {
                "color": c["muted"],
                ":formatter": f"v => Math.round(v).toLocaleString('fr-FR') + ' {m.symbol}'",
            },
        },
        "dataZoom": [{"type": "inside"}],
    }


def patrimoine_options(points: list[tuple[int, dict]], theme: str, m: Money) -> dict:
    o = _base(theme, m)
    o["tooltip"] = _tooltip(theme, m, total=True)
    surface = CHART[theme]["surface"]
    o["series"] = []
    for k in POSTE_ORDER:
        col = poste_color(theme, k)
        o["series"].append(
            {
                "name": POSTE_LABELS[k],
                "type": "line",
                "stack": "patrimoine",
                "showSymbol": False,
                "smooth": False,
                "lineStyle": {"width": 1.5, "color": surface},
                "itemStyle": {"color": col},
                "areaStyle": {"color": col, "opacity": 0.9},
                "emphasis": {"focus": "series"},
                "data": [[t, round(m.conv(p.get(k)), 2)] for t, p in points],
            }
        )
    return o


def gains_options(res: dict, theme: str, m: Money) -> dict:
    o = _base(theme, m)
    o["tooltip"] = _tooltip(theme, m, total=False)
    grid = res["grid"]
    o["series"] = [
        {
            "name": POSTE_LABELS[k],
            "type": "line",
            "showSymbol": False,
            "lineStyle": {"width": 2, "color": poste_color(theme, k)},
            "itemStyle": {"color": poste_color(theme, k)},
            "emphasis": {"focus": "series"},
            "data": [[t, round(m.conv(v), 2)] for t, v in zip(grid, res["series"][k], strict=True)],
        }
        for k in GAIN_ORDER
    ]
    c = CHART[theme]
    o["series"].append(
        {
            "name": "Total",
            "type": "line",
            "showSymbol": False,
            "lineStyle": {"width": 2, "type": "dashed", "color": c["muted"]},
            "itemStyle": {"color": c["muted"]},
            "data": [[t, round(m.conv(v), 2)] for t, v in zip(grid, res["series"]["total"], strict=True)],
            "markLine": {
                "silent": True,
                "symbol": "none",
                "lineStyle": {"color": c["grid"], "type": "solid"},
                "data": [{"yAxis": 0}],
                "label": {"show": False},
            },
        }
    )
    o["tooltip"][":formatter"] = o["tooltip"][":formatter"].replace(
        "if (p.seriesName === 'Total') { return; } ", ""
    )
    return o
