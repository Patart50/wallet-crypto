"""Staking : positions suivies automatiquement (événements on-chain) et positions manuelles.

**Automatique** (Hyperliquid délégation HYPE, lock WCT sur Optimism) : le rendement réel se
calcule à partir des événements importés.

- capital net = dépôts − retraits ;
- une récompense réclamée puis re-lockée (WCT) n'est pas du capital neuf (``classify_restakes``) ;
- APR réel = récompenses ÷ solde staké moyen pondéré par le temps, annualisé ;
- l'écart entre le staké réel et le staké attendu d'après l'historique est signalé.

**Manuel** (autres plateformes) : mode ``apr`` (montant composé à partir d'un taux saisi) ou
``rewards`` (gain = somme des récompenses saisies).

Dates : millisecondes UTC. Le calendrier des récompenses (jour de la semaine, du mois) se
calcule dans le fuseau de l'utilisateur, passé en paramètre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal

from ..money import EPS, HUNDRED, ONE, ZERO

DAY_MS = 86_400_000
YEAR_MS = 365 * DAY_MS
RESTAKE_WINDOW_MS = DAY_MS
RESTAKE_TOL = Decimal("0.005")

CAPITAL_KINDS = ("DEPOSIT", "WITHDRAW", "REWARD", "RESTAKE")


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _dt(ms: int, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz)


# ======================================================================================
# STAKING AUTOMATIQUE
# ======================================================================================
@dataclass
class StakeEvent:
    """Mouvement de staking importé. ``kind`` : DEPOSIT, WITHDRAW, REWARD ; les autres types
    (DELEG, UNDELEG, WITHDRAW_REQ, OTHER:*) sont conservés pour mémoire, sans effet."""

    time_ms: int
    kind: str
    qty: Decimal
    hash: str | None = None


def classify_restakes(events: list[StakeEvent]) -> list[StakeEvent]:
    """Un dépôt est une récompense re-lockée (``RESTAKE``) s'il est dans la même transaction
    qu'une récompense, ou s'il la suit de 24 h au plus pour le même montant (± 0,5 %).
    Limite connue : un dépôt « récompense + ajout » reste compté comme capital."""
    evs = sorted(
        (StakeEvent(e.time_ms, e.kind, e.qty, e.hash) for e in events),
        key=lambda e: (e.time_ms, e.kind != "REWARD"),
    )
    rewards: list[StakeEvent] = []
    used: set[int] = set()
    for e in evs:
        if e.kind == "REWARD":
            rewards.append(e)
        elif e.kind == "DEPOSIT":
            for r in rewards:
                if id(r) in used:
                    continue
                same_tx = bool(r.hash) and r.hash == e.hash
                close = 0 <= e.time_ms - r.time_ms <= RESTAKE_WINDOW_MS and abs(
                    e.qty - r.qty
                ) <= RESTAKE_TOL * max(r.qty, EPS)
                if same_tx or close:
                    used.add(id(r))
                    e.kind = "RESTAKE"
                    break
    return evs


def balance_area(evs: list[StakeEvent], compounding: bool, t_from: int, t_to: int) -> Decimal:
    """Intégrale du solde staké (quantité × ms) sur [t_from, t_to]."""
    bal = area = ZERO
    last: int | None = None
    for e in evs:
        t = e.time_ms
        if last is not None and t > t_from:
            span = min(t, t_to) - max(last, t_from)
            if span > 0:
                area += max(bal, ZERO) * span
        last = t if last is None or t > last else last
        if e.kind in ("DEPOSIT", "RESTAKE") or (e.kind == "REWARD" and compounding):
            bal += e.qty
        elif e.kind == "WITHDRAW":
            bal -= e.qty
        if t >= t_to:
            break
    if last is not None and last < t_to:
        area += max(bal, ZERO) * (t_to - max(last, t_from))
    return area


@dataclass
class AutoStakeMetrics:
    capital: Decimal
    deposits: Decimal
    withdraws: Decimal
    restaked: Decimal
    rewards: Decimal
    pending: Decimal
    rewards_total: Decimal
    gain_pct: Decimal | None
    apr_avg: Decimal | None
    apr_30: Decimal | None
    avg_balance: Decimal | None
    expected: Decimal
    ecart: Decimal | None
    first_ms: int | None
    last_reward_ms: int | None
    n_rewards: int


def stake_auto_metrics(
    events: list[StakeEvent],
    current_qty: Decimal | None,
    pending: Decimal = ZERO,
    compounding: bool = False,
    now_ms: int | None = None,
) -> AutoStakeMetrics:
    """Métriques d'UNE position (source × adresse).

    ``compounding`` : vrai si les récompenses s'ajoutent automatiquement au staké
    (Hyperliquid) ; faux si elles sont versées à part et à réclamer (WCT).
    """
    now_ms = now_ms or _ms(datetime.now(UTC))
    if compounding:
        evs = sorted((StakeEvent(e.time_ms, e.kind, e.qty, e.hash) for e in events), key=lambda e: e.time_ms)
    else:
        evs = classify_restakes(events)
    evs = [e for e in evs if e.kind in CAPITAL_KINDS]

    def total(kind: str) -> Decimal:
        return sum((e.qty for e in evs if e.kind == kind), ZERO)

    dep, wd, rst, rew = total("DEPOSIT"), total("WITHDRAW"), total("RESTAKE"), total("REWARD")
    pending = pending or ZERO
    capital = dep - wd
    expected = capital + rst + (rew if compounding else ZERO)
    ecart = (current_qty - expected) if current_qty is not None else None
    rewards_total = rew + pending
    first = next((e.time_ms for e in evs if e.kind in ("DEPOSIT", "RESTAKE")), None)
    apr_avg = apr_30 = avg_bal = None
    if first is not None and now_ms - first >= DAY_MS:
        span = now_ms - first
        avg_bal = balance_area(evs, compounding, first, now_ms) / span
        if avg_bal > EPS:
            apr_avg = rewards_total / avg_bal * Decimal(YEAR_MS) / span * HUNDRED
        w0 = max(first, now_ms - 30 * DAY_MS)
        r30 = sum((e.qty for e in evs if e.kind == "REWARD" and e.time_ms > w0), ZERO)
        avg30 = balance_area(evs, compounding, w0, now_ms) / max(now_ms - w0, 1)
        if compounding and avg30 > EPS and now_ms - w0 >= DAY_MS:
            apr_30 = r30 / avg30 * Decimal(YEAR_MS) / (now_ms - w0) * HUNDRED
    last_reward = max((e.time_ms for e in evs if e.kind == "REWARD"), default=None)
    return AutoStakeMetrics(
        capital=capital,
        deposits=dep,
        withdraws=wd,
        restaked=rst,
        rewards=rew,
        pending=pending,
        rewards_total=rewards_total,
        gain_pct=(rewards_total / capital * HUNDRED) if capital > EPS else None,
        apr_avg=apr_avg,
        apr_30=apr_30,
        avg_balance=avg_bal,
        expected=expected,
        ecart=ecart,
        first_ms=first,
        last_reward_ms=last_reward,
        n_rewards=sum(1 for e in evs if e.kind == "REWARD"),
    )


# ======================================================================================
# STAKING MANUEL
# ======================================================================================
@dataclass
class ManualStake:
    """Position de staking saisie à la main.

    ``mode`` : ``apr`` (montant composé à partir des taux) ou ``rewards`` (récompenses saisies).
    ``compound_days`` : période de versement (1, 7 ou 30 jours) ; ``reward_dow`` (0 = lundi) en
    hebdomadaire, ``reward_dom`` (1-28) en mensuel. ``fee_pct`` : frais prélevés sur les gains.
    """

    id: int
    crypto: str
    start_ms: int
    mode: str = "apr"
    compound_days: int = 1
    reward_dow: int | None = None
    reward_dom: int | None = None
    rewards_restake: bool = False
    fee_pct: Decimal = ZERO
    entry_price: Decimal | None = None
    end_ms: int | None = None


@dataclass
class StakeRate:
    start_ms: int
    end_ms: int | None
    apr_pct: Decimal


@dataclass
class StakeTx:
    """``kind`` : STAKE (dépôt), UNSTAKE (retrait), REWARD (récompense reçue)."""

    time_ms: int
    kind: str
    qty: Decimal
    effective_ms: int | None = None


def next_reward_date(
    compound_days: int, reward_dow: int | None, reward_dom: int | None, as_of: datetime
) -> datetime:
    """Prochaine échéance de récompense strictement après ``as_of`` (datetime avec fuseau)."""
    midnight = {"hour": 0, "minute": 0, "second": 0, "microsecond": 0}
    if compound_days == 1:
        return (as_of + timedelta(days=1)).replace(**midnight)
    if compound_days == 7 and reward_dow is not None:
        delta = (reward_dow - as_of.weekday()) % 7 or 7
        return (as_of + timedelta(days=delta)).replace(**midnight)
    if compound_days == 30 and reward_dom is not None:
        y, m = as_of.year, as_of.month
        if as_of.day >= reward_dom:
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return datetime(y, m, min(reward_dom, 28), tzinfo=as_of.tzinfo)
    return as_of + timedelta(days=compound_days)


def stake_effective_ms(pos: ManualStake, tx_ms: int, tz: tzinfo = UTC) -> int:
    """Un dépôt ne produit qu'à partir de la 2e échéance qui le suit (la 1re est sautée)."""
    d1 = next_reward_date(pos.compound_days, pos.reward_dow, pos.reward_dom, _dt(tx_ms, tz))
    d2 = next_reward_date(pos.compound_days, pos.reward_dow, pos.reward_dom, d1)
    return _ms(d2)


def _segments_between(rates: list[StakeRate], t0: int, t1: int) -> list[StakeRate]:
    segs = []
    for r in rates:
        if r.end_ms is not None and r.end_ms <= t0:
            continue
        if r.start_ms >= t1:
            continue
        segs.append(StakeRate(max(r.start_ms, t0), r.end_ms, r.apr_pct))
    return segs


def compound_amount(
    initial: Decimal, compound_days: int, segments: list[StakeRate], as_of_ms: int
) -> Decimal:
    """Montant composé : (1 + APR × période / 365) ^ (jours / période) sur chaque segment de taux."""
    amount = initial
    for s in sorted(segments, key=lambda x: x.start_ms):
        t1 = min(s.end_ms or as_of_ms, as_of_ms)
        if t1 <= s.start_ms:
            continue
        n = Decimal(t1 - s.start_ms) / DAY_MS / compound_days
        rate = s.apr_pct / HUNDRED * compound_days / 365
        amount *= (ONE + rate) ** n
    return amount


def _sum(txs: list[StakeTx], kind: str) -> Decimal:
    return sum((t.qty for t in txs if t.kind == kind), ZERO)


def stake_auto_amount(
    pos: ManualStake, rates: list[StakeRate], txs: list[StakeTx], horizon_ms: int, tz: tzinfo = UTC
) -> Decimal:
    """Mode ``apr`` : chaque dépôt est présent dès sa date mais ne produit qu'à partir de sa
    date d'effet ; les retraits sortent au nominal."""
    amount = ZERO
    for t in txs:
        if t.kind == "STAKE":
            if t.time_ms > horizon_ms:
                continue
            eff = t.effective_ms or stake_effective_ms(pos, t.time_ms, tz)
            if eff < horizon_ms:
                amount += compound_amount(
                    t.qty, pos.compound_days, _segments_between(rates, eff, horizon_ms), horizon_ms
                )
            else:
                amount += t.qty
        elif t.kind == "UNSTAKE" and t.time_ms <= horizon_ms:
            amount -= t.qty
    return amount


@dataclass
class ManualStakeMetrics:
    mode: str
    deposited: Decimal
    rewards: Decimal
    pocket: Decimal
    productive: Decimal
    gross_amount: Decimal
    amount: Decimal
    gain_gross: Decimal
    fee_amount: Decimal
    gain: Decimal
    gain_pct: Decimal
    value_init: Decimal | None
    value_now: Decimal | None
    gain_value: Decimal | None
    gain_value_pct: Decimal | None
    apr_current: Decimal | None
    extra: dict = field(default_factory=dict)

    @property
    def held_qty(self) -> Decimal:
        """Quantité détenue au total : montant + récompenses gardées à part."""
        return self.amount + self.pocket


def stake_metrics(
    pos: ManualStake,
    rates: list[StakeRate],
    txs: list[StakeTx],
    price_now: Decimal | None = None,
    now_ms: int | None = None,
    tz: tzinfo = UTC,
) -> ManualStakeMetrics:
    now_ms = now_ms or _ms(datetime.now(UTC))
    horizon = pos.end_ms or now_ms
    deposited = _sum(txs, "STAKE") - _sum(txs, "UNSTAKE")
    rewards = _sum(txs, "REWARD")
    if pos.mode == "rewards":
        gain_gross = rewards
        productive = deposited + (rewards if pos.rewards_restake else ZERO)
        pocket = ZERO if pos.rewards_restake else rewards
        gross_amount = deposited + rewards
    else:
        gross_amount = stake_auto_amount(pos, rates, txs, horizon, tz)
        gain_gross = gross_amount - deposited
        productive = deposited
        pocket = ZERO
    fee_amount = gain_gross * pos.fee_pct / HUNDRED if pos.fee_pct else ZERO
    gain = gain_gross - fee_amount
    if pos.mode == "rewards" and not pos.rewards_restake:
        amount = deposited
        pocket = gain
    else:
        amount = deposited + gain
    value_init = value_now = gain_value = gain_value_pct = None
    if pos.entry_price and price_now:
        value_init = deposited * pos.entry_price
        value_now = (amount + pocket) * price_now
        gain_value = value_now - value_init
        gain_value_pct = gain_value / value_init * HUNDRED if value_init else ZERO
    apr_current = None
    for r in sorted(rates, key=lambda x: x.start_ms):
        if r.end_ms is None:
            apr_current = r.apr_pct
    return ManualStakeMetrics(
        mode=pos.mode,
        deposited=deposited,
        rewards=rewards,
        pocket=pocket,
        productive=productive,
        gross_amount=gross_amount,
        amount=amount,
        gain_gross=gain_gross,
        fee_amount=fee_amount,
        gain=gain,
        gain_pct=(gain / deposited * HUNDRED) if deposited else ZERO,
        value_init=value_init,
        value_now=value_now,
        gain_value=gain_value,
        gain_value_pct=gain_value_pct,
        apr_current=apr_current,
    )
