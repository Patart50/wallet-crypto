"""Hyperliquid : API info publique (https://api.hyperliquid.xyz/info), aucune clé.

Soldes :
- **mode de compte** (``userAbstraction``, repli : réserve USDC spot ≈ marge perp → unifié) ;
- **compte unifié** : un seul solde USDC = USDC spot total (la marge des positions est une
  réserve à l'intérieur) ; l'equity perp n'est **pas** ajoutée, sinon double comptage ;
- **compte standard** : equity perp (``accountValue``) + USDC spot à part (``USDC_SPOT``) ;
- spot : UBTC → BTC, UETH → ETH, USOL → SOL ; positions ouvertes ; recoupement avec la valeur
  officielle du compte (``portfolio``) ;
- staking : vaults (``HLP_VAULTS``, en USD) et délégation HYPE (``HYPE_STAKED`` = délégué
  + non délégué + retraits en file d'attente de 7 jours : tout ce qui vous appartient).

Historique : fills (``userFillsByTime``, Hyperliquid ne sert que les 10 000 derniers : d'où
l'archivage local), funding (``userFunding``), délégation (``delegatorHistory``) et récompenses
de staking (``delegatorRewards``).
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from ..core.assets import AssetLine
from ..core.trades import is_spot_coin
from ..money import ZERO, D, D_opt
from .base import BalanceResult, HistoryBatch, HistoryCursor, Source, SourceError, add_line, register

log = logging.getLogger("wallet_crypto.sources.hyperliquid")

API = "https://api.hyperliquid.xyz/info"
UNIT_MAP = {"UBTC": "BTC", "UETH": "ETH", "USOL": "SOL"}
UNIFIED_MODES = ("unifiedaccount", "portfoliomargin")
FILLS_PAGE = 2000
MAX_PAGES = 40
FILLS_CAP = 10_000
STABLE_QUOTES = ("USDC", "USDT0", "USDT", "USDH", "USDE")


def normalize_coin(coin: str | None) -> str:
    c = str(coin or "")
    if c in ("USDC", "USDT"):
        return c
    return UNIT_MAP.get(c, c)


def clean_address(address: str) -> str:
    a = (address or "").strip()
    return a[3:].strip() if a.lower().startswith("hl:") else a


# ---------------------------------------------------------------- analyse des réponses
def parse_perp(res: dict) -> tuple[dict, list[dict]]:
    """``clearinghouseState`` → (résumé du compte perp, positions ouvertes)."""
    ms = res.get("marginSummary") or {}
    equity = D(ms.get("accountValue"))
    margin = D(ms.get("totalMarginUsed"))
    positions, upnl = [], ZERO
    for ap in res.get("assetPositions") or []:
        p = ap.get("position") or {}
        szi = D(p.get("szi"))
        if szi == 0:
            continue
        u = D(p.get("unrealizedPnl"))
        upnl += u
        lev = p.get("leverage") or {}
        positions.append(
            {
                "coin": normalize_coin(p.get("coin")),
                "side": "LONG" if szi > 0 else "SHORT",
                "size": abs(szi),
                "entry": D(p.get("entryPx")),
                "value": D(p.get("positionValue")),
                "upnl": u,
                "lev": D_opt(lev.get("value") if isinstance(lev, dict) else lev),
                "liq_px": D_opt(p.get("liquidationPx")),
                "roe": D(p.get("returnOnEquity")) * 100,
            }
        )
    summary = {
        "equity": equity,
        "withdrawable": D(res.get("withdrawable")),
        "margin_used": margin,
        "upnl": upnl,
        "n_pos": len(positions),
    }
    return summary, positions


def parse_mode(res) -> str:
    """Réponse de ``userAbstraction`` → nom du mode en minuscules ('' si inconnu)."""
    if isinstance(res, str):
        return res.strip().lower()
    if isinstance(res, dict):
        for k in ("abstraction", "mode", "type", "userAbstraction"):
            if isinstance(res.get(k), str):
                return res[k].strip().lower()
    return ""


def parse_official_value(res) -> Decimal | None:
    """Réponse ``portfolio`` → dernière valeur de compte officielle (fenêtre ``day``)."""
    try:
        for window, data in res:
            if window == "day":
                hist = data.get("accountValueHistory") or []
                return D(hist[-1][1]) if hist else None
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def usdc_line(perp: dict, spot_usdc: tuple[Decimal, Decimal] | None, unified: bool) -> AssetLine:
    if unified and spot_usdc is not None:
        total, hold = spot_usdc
        return AssetLine(
            "USDC",
            total,
            total,
            "hl_unified",
            extra={
                "mode": "unified",
                "hold": hold,
                "transferable": max(ZERO, total - hold),
                "margin_used": perp["margin_used"],
                "upnl": perp["upnl"],
                "n_pos": perp["n_pos"],
            },
        )
    return AssetLine(
        "USDC",
        perp["equity"],
        perp["equity"],
        "hl_perp",
        extra={
            "mode": "standard",
            "withdrawable": perp["withdrawable"],
            "margin_used": perp["margin_used"],
            "upnl": perp["upnl"],
            "n_pos": perp["n_pos"],
        },
    )


def parse_delegator_summary(res: dict) -> AssetLine | None:
    d, u, w = D(res.get("delegated")), D(res.get("undelegated")), D(res.get("totalPendingWithdrawal"))
    tot = d + u + w
    if tot <= 0:
        return None
    return AssetLine(
        "HYPE_STAKED",
        tot,
        None,
        "hl_deleg",
        extra={
            "delegated": d,
            "undelegated": u,
            "pending_withdrawal": w,
            "n_pending_withdrawals": int(res.get("nPendingWithdrawals") or 0),
        },
    )


def parse_fill(addr: str, f: dict) -> dict:
    return {
        "address": addr,
        "tid": int(f["tid"]),
        "oid": int(f["oid"]) if f.get("oid") is not None else None,
        "coin": f.get("coin"),
        "side": f.get("side"),
        "px": D(f.get("px")),
        "sz": D(f.get("sz")),
        "dir": f.get("dir"),
        "start_position": D(f.get("startPosition")),
        "closed_pnl": D(f.get("closedPnl")),
        "fee": D(f.get("fee")),
        "fee_token": f.get("feeToken"),
        "builder_fee": D(f.get("builderFee")),
        "time_ms": int(f["time"]),
        "hash": f.get("hash"),
        "crossed": f.get("crossed"),
        "liquidation": bool(f.get("liquidation")),
        "is_spot": is_spot_coin(f.get("coin")),
    }


def parse_funding(addr: str, x: dict) -> dict | None:
    d = x.get("delta") or {}
    if d.get("type", "funding") != "funding":
        return None
    return {
        "address": addr,
        "time_ms": int(x["time"]),
        "coin": d.get("coin"),
        "usdc": D(d.get("usdc")),
        "szi": D_opt(d.get("szi")),
        "rate": D_opt(d.get("fundingRate")),
        "hash": x.get("hash"),
    }


def parse_stake_history(addr: str, hist: list) -> list[dict]:
    """``delegatorHistory`` : ``cDeposit`` = dépôt (spot → staking), ``withdrawal`` finalisé =
    retrait, le reste pour mémoire. Type inconnu → ``OTHER:*`` et avertissement."""
    out = []
    for x in hist or []:
        t, h, delta = int(x.get("time") or 0), x.get("hash"), x.get("delta") or {}
        for key, d in delta.items():
            d = d if isinstance(d, dict) else {}
            if key == "cDeposit":
                kind = "DEPOSIT"
            elif key == "withdrawal":
                kind = (
                    "WITHDRAW" if str(d.get("phase", "finalized")).lower() == "finalized" else "WITHDRAW_REQ"
                )
            elif key == "delegate":
                kind = "UNDELEG" if d.get("isUndelegate") else "DELEG"
            else:
                kind = f"OTHER:{key}"[:20]
                log.warning("delegatorHistory : type inconnu %r (%s)", key, addr)
            out.append(
                {
                    "source": "HL_HYPE",
                    "address": addr,
                    "asset": "HYPE",
                    "time_ms": t,
                    "kind": kind,
                    "qty": D(d.get("amount")),
                    "hash": h,
                    "ext_id": f"hl:{addr}:{t}:{h}:{kind}"[:190],
                    "detail": (str(d.get("validator") or d.get("phase") or ""))[:200] or None,
                }
            )
    return out


def parse_rewards(addr: str, rews: list) -> list[dict]:
    out = []
    for x in rews or []:
        t, src = int(x.get("time") or 0), str(x.get("source") or "delegation")
        amt = D(x.get("totalAmount"))
        if amt <= 0:
            continue
        out.append(
            {
                "source": "HL_HYPE",
                "address": addr,
                "asset": "HYPE",
                "time_ms": t,
                "kind": "REWARD",
                "qty": amt,
                "hash": None,
                "ext_id": f"hlr:{addr}:{t}:{src}"[:190],
                "detail": src,
            }
        )
    return out


def parse_spot_pairs(meta) -> dict[str, dict]:
    """``spotMeta`` → {nom de paire : {base, raw, quote}} (``@107`` → HYPE)."""
    tokens = {t.get("index"): t.get("name") for t in (meta or {}).get("tokens") or []}
    pairs = {}
    for u in (meta or {}).get("universe") or []:
        tk = u.get("tokens") or []
        if len(tk) != 2:
            continue
        raw, quote = tokens.get(tk[0]), tokens.get(tk[1])
        if not raw or not u.get("name"):
            continue
        pairs[u["name"]] = {"base": normalize_coin(raw), "raw": raw, "quote": quote}
    return pairs


def paginate_by_time(
    fetch, key_fn, time_fn, start_ms: int, end_ms: int, page_limit: int | None = None
) -> list:
    """Pagination adaptative : lot croissant → on avance le début ; décroissant → on recule la
    fin. Dédoublonnage par clé ; arrêt quand un lot n'apporte rien ou est incomplet."""
    seen: dict = {}
    start, end = start_ms, end_ms
    for _ in range(MAX_PAGES):
        batch = fetch(start, end) or []
        if not isinstance(batch, list):
            break
        new = 0
        for it in batch:
            k = key_fn(it)
            if k not in seen:
                seen[k] = it
                new += 1
        if not batch or new == 0 or (page_limit and len(batch) < page_limit):
            break
        times = [time_fn(it) for it in batch]
        if times[0] <= times[-1]:
            start = max(times)
        else:
            end = min(times)
        if start > end:
            break
    return list(seen.values())


# ---------------------------------------------------------------- source
@register
class HyperliquidSource(Source):
    network = "HL"
    label = "Hyperliquid"

    def post(self, payload: dict, required: bool = True):
        try:
            return self.http.post_json(API, payload, timeout=15)
        except Exception as exc:
            if required:
                raise SourceError(f"Hyperliquid {payload.get('type')} : {exc}") from exc
            log.warning("Hyperliquid %s (toléré) : %s", payload.get("type"), exc)
            return None

    def fetch_balances(self, address: str, track_staking: bool = True) -> BalanceResult:
        addr = clean_address(address)
        lines: dict[str, AssetLine] = {}
        mode = parse_mode(self.post({"type": "userAbstraction", "user": addr}, required=False))
        perp, positions = parse_perp(self.post({"type": "clearinghouseState", "user": addr}) or {})
        spot = self.post({"type": "spotClearinghouseState", "user": addr}) or {}
        spot_usdc = None
        for b in spot.get("balances") or []:
            coin = normalize_coin(b.get("coin"))
            total, hold = D(b.get("total")), D(b.get("hold"))
            if total <= 0:
                continue
            if coin == "USDC":
                spot_usdc = (total, hold)
            elif coin == "USDT":
                add_line(lines, "USDT_SPOT", total, total, "hl_spot")
            else:
                add_line(lines, coin, total, None, "hl_spot")
        if (
            not mode
            and spot_usdc
            and perp["margin_used"] > 0
            and abs(spot_usdc[1] - perp["margin_used"]) <= Decimal("0.02") * perp["margin_used"]
        ):
            mode = "unifiedaccount(heuristique)"
        unified = mode.startswith(UNIFIED_MODES)
        usdc = usdc_line(perp, spot_usdc, unified)
        if not unified and spot_usdc:
            add_line(lines, "USDC_SPOT", spot_usdc[0], spot_usdc[0], "hl_spot")
        usdc.extra["official_value"] = parse_official_value(
            self.post({"type": "portfolio", "user": addr}, required=False)
        )
        usdc.extra["account_mode"] = mode or "inconnu"
        lines["USDC"] = usdc
        if track_staking:
            vaults = self.post({"type": "userVaultEquities", "user": addr}, required=False)
            if isinstance(vaults, list):
                for v in vaults:
                    eq = D(v.get("equity"))
                    if eq > 0:
                        add_line(lines, "HLP_VAULTS", eq, eq, "hl_vault")
            deleg = self.post({"type": "delegatorSummary", "user": addr}, required=False)
            if isinstance(deleg, dict):
                line = parse_delegator_summary(deleg)
                if line:
                    lines["HYPE_STAKED"] = line
        return BalanceResult(lines, positions)

    def fetch_history(self, address: str, track_staking: bool, cursor: HistoryCursor) -> HistoryBatch:
        addr = clean_address(address)
        now = int(time.time() * 1000)
        batch = HistoryBatch()

        start = cursor.last_fill_ms or 0
        raw = paginate_by_time(
            lambda st, en: self.post(
                {
                    "type": "userFillsByTime",
                    "user": addr,
                    "startTime": st,
                    "endTime": en,
                    "aggregateByTime": False,
                }
            ),
            key_fn=lambda f: int(f["tid"]),
            time_fn=lambda f: int(f["time"]),
            start_ms=start,
            end_ms=now,
            page_limit=FILLS_PAGE,
        )
        batch.fills = [parse_fill(addr, f) for f in raw]
        if start == 0 and len(raw) >= FILLS_CAP:
            batch.warnings.append(
                "10 000 fills reçus au premier import : c'est la limite de Hyperliquid, les trades plus "
                "anciens ne sont pas récupérables."
            )

        fstart = cursor.last_funding_ms or 0
        raw_f = paginate_by_time(
            lambda st, en: self.post({"type": "userFunding", "user": addr, "startTime": st, "endTime": en}),
            key_fn=lambda x: (int(x["time"]), (x.get("delta") or {}).get("coin")),
            time_fn=lambda x: int(x["time"]),
            start_ms=fstart,
            end_ms=now,
        )
        batch.funding = [p for p in (parse_funding(addr, x) for x in raw_f) if p]

        if track_staking:
            hist = self.post({"type": "delegatorHistory", "user": addr}, required=False)
            rews = self.post({"type": "delegatorRewards", "user": addr}, required=False)
            batch.stake_events = parse_stake_history(
                addr, hist if isinstance(hist, list) else []
            ) + parse_rewards(addr, rews if isinstance(rews, list) else [])
        return batch


def load_market(http) -> tuple[dict[str, dict], dict[str, Decimal]]:
    """Paires spot (``spotMeta``) et prix médians (``allMids``). Tolère l'échec."""
    pairs: dict[str, dict] = {}
    mids: dict[str, Decimal] = {}
    try:
        pairs = parse_spot_pairs(http.post_json(API, {"type": "spotMeta"}, timeout=15))
    except Exception as exc:
        log.warning("spotMeta : %s", exc)
    try:
        mids = {k: D(v) for k, v in (http.post_json(API, {"type": "allMids"}, timeout=15) or {}).items()}
    except Exception as exc:
        log.warning("allMids : %s", exc)
    return pairs, mids
