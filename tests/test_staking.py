from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from conftest import d
from wallet_crypto.core.staking import (
    DAY_MS,
    ManualStake,
    StakeEvent,
    StakeRate,
    StakeTx,
    classify_restakes,
    compound_amount,
    next_reward_date,
    stake_auto_metrics,
    stake_effective_ms,
    stake_metrics,
)

T0 = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)


def test_restake_same_tx_or_within_24h():
    evs = [
        StakeEvent(T0, "DEPOSIT", d(1000), "0xa"),
        StakeEvent(T0 + 7 * DAY_MS, "REWARD", d(10), "0xb"),
        StakeEvent(T0 + 7 * DAY_MS + 3600_000, "DEPOSIT", d("10.02"), "0xc"),  # re-lock (±0,5 %)
        StakeEvent(T0 + 14 * DAY_MS, "REWARD", d(12), "0xd"),
        StakeEvent(T0 + 14 * DAY_MS, "DEPOSIT", d(500), "0xd"),  # même transaction
        StakeEvent(T0 + 21 * DAY_MS, "REWARD", d(8), "0xe"),
        StakeEvent(T0 + 23 * DAY_MS, "DEPOSIT", d(8), "0xf"),  # 48 h plus tard : capital
    ]
    kinds = [e.kind for e in classify_restakes(evs)]
    assert kinds.count("RESTAKE") == 2
    assert kinds[-1] == "DEPOSIT"


def test_auto_metrics_compounding_constant_balance():
    """1 000 HYPE stakés, 1 HYPE de récompense par jour pendant 365 jours (recomposé).
    Solde moyen ≈ 1 000 + 365/2 ; APR réel ≈ 365 / 1 182,5 ≈ 30,9 %."""
    evs = [StakeEvent(T0, "DEPOSIT", d(1000))]
    evs += [StakeEvent(T0 + (i + 1) * DAY_MS, "REWARD", d(1)) for i in range(365)]
    now = T0 + 365 * DAY_MS
    m = stake_auto_metrics(evs, current_qty=d(1365), compounding=True, now_ms=now)
    assert m.capital == d(1000)
    assert m.rewards_total == d(365)
    assert m.expected == d(1365) and m.ecart == 0
    assert m.gain_pct == d("36.5")
    # solde moyen exact : 1000 + (0+1+…+364)/365 = 1000 + 182
    assert m.avg_balance == d(1182)
    assert abs(m.apr_avg - d(365) / d(1182) * 100) < d("1e-20")
    # 30 derniers jours : 30 récompenses, solde moyen 1 349,5 → 365 / 1 349,5 ≈ 27,05 %
    assert abs(m.apr_30 - d(365) / d("1349.5") * 100) < d("1e-20")
    assert m.n_rewards == 365


def test_auto_metrics_wct_not_compounding():
    evs = [
        StakeEvent(T0, "DEPOSIT", d(100), "a"),
        StakeEvent(T0 + 7 * DAY_MS, "REWARD", d(2), "b"),
        StakeEvent(T0 + 7 * DAY_MS + 60_000, "DEPOSIT", d(2), "c"),  # récompense re-lockée
    ]
    m = stake_auto_metrics(evs, current_qty=d(102), pending=d(1), compounding=False, now_ms=T0 + 10 * DAY_MS)
    assert m.capital == d(100)
    assert m.restaked == d(2)
    assert m.rewards_total == d(3)
    assert m.expected == d(102) and m.ecart == 0
    assert m.apr_30 is None  # pas d'APR 30 j sans recomposition (récompenses à réclamer)


def test_auto_metrics_too_recent_no_apr():
    m = stake_auto_metrics([StakeEvent(T0, "DEPOSIT", d(10))], d(10), now_ms=T0 + 3600_000)
    assert m.apr_avg is None and m.avg_balance is None


def test_ecart_signale():
    m = stake_auto_metrics(
        [StakeEvent(T0, "DEPOSIT", d(10))], d(12), compounding=True, now_ms=T0 + 2 * DAY_MS
    )
    assert m.ecart == d(2)


def test_next_reward_dates():
    paris = ZoneInfo("Europe/Paris")
    as_of = datetime(2026, 3, 10, 15, 0, tzinfo=paris)  # mardi
    assert next_reward_date(1, None, None, as_of) == datetime(2026, 3, 11, tzinfo=paris)
    assert next_reward_date(7, 3, None, as_of) == datetime(2026, 3, 12, tzinfo=paris)  # jeudi
    assert next_reward_date(7, 1, None, as_of) == datetime(2026, 3, 17, tzinfo=paris)  # mardi suivant
    assert next_reward_date(30, None, 5, as_of) == datetime(2026, 4, 5, tzinfo=paris)
    assert next_reward_date(30, None, 15, as_of) == datetime(2026, 3, 15, tzinfo=paris)
    dec = datetime(2026, 12, 20, tzinfo=paris)
    assert next_reward_date(30, None, 5, dec) == datetime(2027, 1, 5, tzinfo=paris)


def test_compound_one_year_daily():
    """APR 10 %, composé chaque jour pendant 365 jours : (1 + 0,1/365)^365 ≈ 1,105156."""
    seg = [StakeRate(T0, None, d(10))]
    amount = compound_amount(d(1000), 1, seg, T0 + 365 * DAY_MS)
    expected = (1 + Decimal("0.1") / 365) ** 365 * 1000
    assert abs(amount - expected) < d("1e-30")
    assert d("1105.15") < amount < d("1105.16")


def test_rate_change_segments():
    seg = [StakeRate(T0, T0 + 100 * DAY_MS, d(10)), StakeRate(T0 + 100 * DAY_MS, None, d(0))]
    a = compound_amount(d(100), 1, seg, T0 + 365 * DAY_MS)
    b = compound_amount(d(100), 1, [StakeRate(T0, None, d(10))], T0 + 100 * DAY_MS)
    assert a == b  # taux nul après 100 jours


def test_manual_apr_mode_effective_delay():
    pos = ManualStake(1, "DOT", T0, mode="apr", compound_days=1)
    eff = stake_effective_ms(pos, T0 + 3600_000)
    assert eff == T0 + 2 * DAY_MS  # 2e minuit après le dépôt
    rates = [StakeRate(T0, None, d(10))]
    txs = [StakeTx(T0 + 3600_000, "STAKE", d(100))]
    m = stake_metrics(pos, rates, txs, now_ms=T0 + DAY_MS)  # avant la date d'effet
    assert m.amount == d(100) and m.gain == 0
    m2 = stake_metrics(pos, rates, txs, price_now=d(5), now_ms=T0 + 367 * DAY_MS)
    assert d("110.5") < m2.amount < d("110.6")
    assert m2.apr_current == d(10)


def test_manual_rewards_mode_no_double_count():
    """Correctif par rapport au module d'origine : sans réintégration, les récompenses sont
    une poche séparée, comptée une seule fois dans la quantité détenue."""
    pos = ManualStake(1, "DOT", T0, mode="rewards", rewards_restake=False, entry_price=d(4))
    txs = [
        StakeTx(T0, "STAKE", d(100)),
        StakeTx(T0 + DAY_MS, "REWARD", d(3)),
        StakeTx(T0 + 2 * DAY_MS, "UNSTAKE", d(20)),
    ]
    m = stake_metrics(pos, [], txs, price_now=d(5), now_ms=T0 + 3 * DAY_MS)
    assert m.deposited == d(80)
    assert m.amount == d(80) and m.pocket == d(3)
    assert m.held_qty == d(83)
    assert m.gain == d(3) and m.gain_pct == d("3.75")
    assert m.value_now == d(415) and m.value_init == d(320)


def test_manual_rewards_restake_and_fee():
    pos = ManualStake(1, "DOT", T0, mode="rewards", rewards_restake=True, fee_pct=d(10))
    txs = [StakeTx(T0, "STAKE", d(100)), StakeTx(T0 + DAY_MS, "REWARD", d(10))]
    m = stake_metrics(pos, [], txs, now_ms=T0 + 2 * DAY_MS)
    assert m.fee_amount == d(1) and m.gain == d(9)
    assert m.amount == d(109) and m.pocket == 0 and m.held_qty == d(109)
    assert m.productive == d(110)
