"""Hold : quantité réelle (wallets) et prix moyen pondéré reconstitué.

La quantité vient toujours des soldes réels des wallets. Le prix de revient se reconstitue à
partir des achats spot Hyperliquid (frais déduits) et des achats saisis à la main (CEX, DEX,
transfert). Types de mouvement :

- ``BUY`` / ``SELL`` : achat, vente (prix requis) ; une vente ne change pas le PMP ;
- ``FEE`` : frais de transfert payés en token : la quantité sort, le coût reste (le PMP monte) ;
  si l'inventaire tombe à zéro, le coût restant devient une perte réalisée ;
- ``OUT`` / ``IN`` : passage vers / depuis le staking : sortie au PMP sans résultat, retour au
  PMP mis de côté.

Les récompenses de staking réclamées et gardées en wallet ont un coût nul ; elles sont déjà
comptées comme gain dans le staking, donc pas comme latent ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..money import EPS, HUNDRED, ZERO
from .assets import AssetLine, asset_base, asset_category

STABLE_QUOTES = ("USDC", "USDT0", "USDT", "USDH", "USDE")


@dataclass
class HoldTx:
    time_ms: int
    kind: str  # BUY, SELL, FEE, OUT, IN
    qty: Decimal
    price: Decimal | None = None
    src: str = "manuel"  # hl_spot, manuel, staking


@dataclass
class HoldPosition:
    real: Decimal
    inv_qty: Decimal
    pmp: Decimal
    covered: Decimal
    coverage_pct: Decimal | None
    from_rewards: Decimal
    unknown: Decimal
    excess: Decimal
    realized: Decimal
    oversold: Decimal
    value: Decimal | None
    latent: Decimal | None
    latent_pct: Decimal | None
    staked_cost_qty: Decimal
    staked_cost: Decimal
    history: list[dict] = field(default_factory=list)

    @property
    def cost_covered(self) -> Decimal:
        return self.covered * self.pmp


_ORDER = {"BUY": 0, "IN": 0}


def hold_position(
    real_qty: Decimal,
    txs: list[HoldTx],
    price_now: Decimal | None = None,
    rewards_free: Decimal = ZERO,
) -> HoldPosition:
    qty = cost = realized = oversold = ZERO
    pool_q = pool_c = ZERO
    history: list[dict] = []
    for t in sorted(txs, key=lambda x: (x.time_ms, _ORDER.get(x.kind, 1))):
        q, k = t.qty, t.kind
        if q <= 0:
            continue
        q_b, real_b, over_b = qty, realized, oversold
        pmp_b = cost / qty if qty > EPS else ZERO
        if k == "BUY":
            qty += q
            cost += q * (t.price or ZERO)
        elif k == "SELL":
            s = min(q, qty)
            if s > 0:
                pmp = cost / qty
                realized += s * ((t.price or ZERO) - pmp)
                cost -= s * pmp
                qty -= s
            oversold += q - s
        elif k == "FEE":
            qty -= min(q, qty)
            if qty <= EPS and cost:
                realized -= cost
                cost = ZERO
                qty = ZERO
        elif k == "OUT":
            s = min(q, qty)
            if s > 0:
                pmp = cost / qty
                pool_q += s
                pool_c += s * pmp
                cost -= s * pmp
                qty -= s
        elif k == "IN":
            s = min(q, pool_q)
            if s > 0:
                pp = pool_c / pool_q
                qty += s
                cost += s * pp
                pool_q -= s
                pool_c -= s * pp
        else:
            continue
        history.append(
            {
                "time_ms": t.time_ms,
                "kind": k,
                "src": t.src,
                "qty": q,
                "price": t.price,
                "qty_before": q_b,
                "qty_after": qty,
                "pmp_before": pmp_b,
                "pmp_after": cost / qty if qty > EPS else ZERO,
                "realized": realized - real_b,
                "oversold": oversold - over_b,
            }
        )
    pmp = cost / qty if qty > EPS else ZERO
    real = real_qty or ZERO
    covered = min(qty, real)
    uncovered = max(real - qty, ZERO)
    from_rewards = min(uncovered, max(rewards_free or ZERO, ZERO))
    value = latent = latent_pct = None
    if price_now:
        value = real * price_now
        if covered > EPS:
            latent = covered * (price_now - pmp)
            latent_pct = (price_now - pmp) / pmp * HUNDRED if pmp else None
    return HoldPosition(
        real=real,
        inv_qty=qty,
        pmp=pmp,
        covered=covered,
        coverage_pct=(covered / real * HUNDRED) if real > EPS else None,
        from_rewards=from_rewards,
        unknown=uncovered - from_rewards,
        excess=max(qty - real, ZERO),
        realized=realized,
        oversold=oversold,
        value=value,
        latent=latent,
        latent_pct=latent_pct,
        staked_cost_qty=pool_q,
        staked_cost=pool_c,
        history=history,
    )


def spot_fill_tx(fill: dict, pair: dict) -> HoldTx:
    """Fill spot Hyperliquid → achat ou vente au prix NET de frais.

    Frais spot : prélevés dans le token reçu (achat) ou en monnaie de cotation (vente) ;
    frais de builder en monnaie de cotation. ``pair`` : {base, raw, quote}."""
    raw = pair["raw"]
    sz, px = fill["sz"], fill["px"]
    fee, bfee = fill.get("fee") or ZERO, fill.get("builder_fee") or ZERO
    fee_in_base = (fill.get("fee_token") or "") == raw
    if fill["side"] == "B":
        q = sz - (fee if fee_in_base else ZERO)
        cost = px * sz + (ZERO if fee_in_base else fee) + bfee
        return HoldTx(int(fill["time_ms"]), "BUY", q, cost / q if q > 0 else px, "hl_spot")
    proceeds = px * sz - (fee * px if fee_in_base else fee) - bfee
    return HoldTx(int(fill["time_ms"]), "SELL", sz, proceeds / sz if sz > 0 else px, "hl_spot")


@dataclass
class HoldInputs:
    real: dict[str, dict]  # base -> {qty, staked, where}
    txs: dict[str, list[HoldTx]]
    n_src: dict[str, dict[str, int]]
    rewards_free: dict[str, Decimal]
    prices: dict[str, Decimal]  # prix noté à la sync, repli
    skipped_pairs: list[str]


def build_hold_inputs(
    wallets: list[tuple[str, str, dict[str, AssetLine]]],
    manual_txs: list[tuple[str, HoldTx]],
    spot_fills: list[dict],
    spot_pairs: dict[str, dict],
    stake_events: dict[tuple[str, str], list],
    pending: dict[str, Decimal] | None = None,
    include_staked: bool = False,
) -> HoldInputs:
    """Assemble les données du hold.

    ``wallets`` : [(libellé, réseau, lignes)] ; ``manual_txs`` : [(crypto, mouvement saisi)] ;
    ``stake_events`` : {(source, actif): [StakeEvent]} ; ``pending`` : réclamable par actif.

    ``include_staked`` : ajoute le staké et le réclamable à la quantité (latent de toute la
    position) ; les passages wallet ↔ staking deviennent internes et toutes les récompenses
    sont des quantités à coût nul. Vue seulement : le patrimoine ne change pas.
    """
    from .staking import classify_restakes  # import local : évite un cycle au chargement

    real: dict[str, dict] = {}
    prices: dict[str, Decimal] = {}
    pend = dict(pending or {})
    for label, network, lines in wallets:
        for coin, line in lines.items():
            cat = asset_category(coin)
            staked = cat == "stake" and coin.upper() != "HLP_VAULTS"
            if not (cat == "hold" or (include_staked and staked)):
                continue
            if line.qty <= EPS:
                continue
            b = asset_base(coin)
            if line.px_sync:
                prices[b] = line.px_sync
            elif line.val is not None:
                prices.setdefault(b, line.val / line.qty)
            e = real.setdefault(b, {"qty": ZERO, "staked": ZERO, "where": []})
            e["qty"] += line.qty
            if staked:
                e["staked"] += line.qty
            e["where"].append(f"{label} ({network}{' staké' if staked else ''}) {line.qty}")

    txs: dict[str, list[HoldTx]] = {}
    n_src: dict[str, dict[str, int]] = {}
    for crypto, tx in manual_txs:
        c = crypto.upper()
        txs.setdefault(c, []).append(tx)
        n_src.setdefault(c, {"hl": 0, "man": 0})["man"] += 1
    skipped: set[str] = set()
    for f in spot_fills:
        pair = spot_pairs.get(f["coin"])
        if not pair or pair.get("quote") not in STABLE_QUOTES:
            skipped.add(f["coin"])
            continue
        c = pair["base"]
        txs.setdefault(c, []).append(spot_fill_tx(f, pair))
        n_src.setdefault(c, {"hl": 0, "man": 0})["hl"] += 1

    rewards_free: dict[str, Decimal] = {}
    for (source, asset), evs in stake_events.items():
        if not evs:
            continue
        compounding = source == "HL_HYPE"
        evs = list(evs) if compounding else classify_restakes(evs)
        rew = sum((e.qty for e in evs if e.kind == "REWARD"), ZERO)
        if include_staked:
            rewards_free[asset] = rewards_free.get(asset, ZERO) + rew + pend.pop(asset, ZERO)
            continue
        for e in evs:
            if e.kind == "DEPOSIT":
                txs.setdefault(asset, []).append(HoldTx(e.time_ms, "OUT", e.qty, None, "staking"))
            elif e.kind == "WITHDRAW":
                txs.setdefault(asset, []).append(HoldTx(e.time_ms, "IN", e.qty, None, "staking"))
        dep = sum((e.qty for e in evs if e.kind == "DEPOSIT"), ZERO)
        wd = sum((e.qty for e in evs if e.kind == "WITHDRAW"), ZERO)
        if compounding:  # Hyperliquid : les récompenses ressortent avec les retraits
            free = max(wd - dep, ZERO)
        else:  # WCT : réclamées au wallet, moins celles re-lockées
            free = max(rew - sum((e.qty for e in evs if e.kind == "RESTAKE"), ZERO), ZERO)
        rewards_free[asset] = rewards_free.get(asset, ZERO) + free
    return HoldInputs(real, txs, n_src, rewards_free, prices, sorted(skipped))
