"""Schéma SQLite (SQLAlchemy 2).

Montants stockés en **texte décimal** (``DecimalText``) : le type numérique de SQLite arrondit
en flottant (wallet D-008). Dates en millisecondes UTC (entiers).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..money import D, dumps, to_str

SCHEMA_VERSION = 1


class DecimalText(TypeDecorator):
    """``Decimal`` ↔ texte exact."""

    impl = String(80)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return to_str(D(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


def _revive(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _revive(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_revive(v) for v in o]
    if isinstance(o, str) and _NUMERIC.match(o):
        return Decimal(o)
    return o


class JsonText(TypeDecorator):
    """Dictionnaire libre (détails d'une source). Les ``Decimal`` restent exacts."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else dumps(value)

    def process_result_value(self, value, dialect):
        return None if value is None else _revive(json.loads(value))


Dec = DecimalText


class Base(DeclarativeBase):
    pass


class Wallet(Base):
    """Une adresse suivie sur un réseau. La même adresse 0x peut être suivie en HL et en EVM."""

    __tablename__ = "wallet"
    __table_args__ = (UniqueConstraint("address", "network", name="uq_wallet_address_network"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_name: Mapped[str] = mapped_column(String(60), default="Mon wallet")
    label: Mapped[str] = mapped_column(String(60))
    network: Mapped[str] = mapped_column(String(10))
    address: Mapped[str] = mapped_column(String(100), index=True)
    track_staking: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_trading: Mapped[bool] = mapped_column(Boolean, default=False)  # D-011
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class BalanceLine(Base):
    """Solde réel d'un actif dans un wallet, à la dernière synchronisation réussie."""

    __tablename__ = "balance_line"
    __table_args__ = (UniqueConstraint("wallet_id", "coin", name="uq_balance_wallet_coin"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallet.id", ondelete="CASCADE"), index=True)
    coin: Mapped[str] = mapped_column(String(40))
    qty: Mapped[Decimal] = mapped_column(Dec)
    val: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    src: Mapped[str] = mapped_column(String(30), default="")
    px_sync: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JsonText, nullable=True)
    synced_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class HlPosition(Base):
    __tablename__ = "hl_position"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallet.id", ondelete="CASCADE"), index=True)
    coin: Mapped[str] = mapped_column(String(30))
    side: Mapped[str] = mapped_column(String(5))
    size: Mapped[Decimal] = mapped_column(Dec)
    entry: Mapped[Decimal] = mapped_column(Dec)
    value: Mapped[Decimal] = mapped_column(Dec)
    upnl: Mapped[Decimal] = mapped_column(Dec)
    lev: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    liq_px: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    roe: Mapped[Decimal] = mapped_column(Dec)


class HlFill(Base):
    """Fill Hyperliquid archivé : Hyperliquid ne sert que les 10 000 derniers."""

    __tablename__ = "hl_fill"
    __table_args__ = (UniqueConstraint("address", "tid", name="uq_hl_fill_address_tid"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    tid: Mapped[int] = mapped_column(BigInteger)
    oid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coin: Mapped[str] = mapped_column(String(30), index=True)
    side: Mapped[str] = mapped_column(String(2))
    px: Mapped[Decimal] = mapped_column(Dec)
    sz: Mapped[Decimal] = mapped_column(Dec)
    dir: Mapped[str | None] = mapped_column(String(40), nullable=True)
    start_position: Mapped[Decimal] = mapped_column(Dec)
    closed_pnl: Mapped[Decimal] = mapped_column(Dec)
    fee: Mapped[Decimal] = mapped_column(Dec)
    fee_token: Mapped[str | None] = mapped_column(String(12), nullable=True)
    builder_fee: Mapped[Decimal] = mapped_column(Dec)
    time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    crossed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    liquidation: Mapped[bool] = mapped_column(Boolean, default=False)
    is_spot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class HlFunding(Base):
    """Funding Hyperliquid : ``usdc`` négatif = payé, positif = reçu."""

    __tablename__ = "hl_funding"
    __table_args__ = (UniqueConstraint("address", "time_ms", "coin", name="uq_hl_funding"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    coin: Mapped[str] = mapped_column(String(30))
    usdc: Mapped[Decimal] = mapped_column(Dec)
    szi: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    rate: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    hash: Mapped[str | None] = mapped_column(String(80), nullable=True)


class StakeEventRow(Base):
    """Mouvement de staking on-chain importé (HL_HYPE, WCT_OP). ``ext_id`` : import idempotent."""

    __tablename__ = "stake_event"
    __table_args__ = (UniqueConstraint("ext_id", name="uq_stake_event_ext_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    address: Mapped[str] = mapped_column(String(64), index=True)
    asset: Mapped[str] = mapped_column(String(20))
    time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    qty: Mapped[Decimal] = mapped_column(Dec)
    hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ext_id: Mapped[str] = mapped_column(String(190))
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Snapshot(Base):
    """Patrimoine global à chaque synchronisation, en USD. Évolution brute : inclut les dépôts
    et retraits externes."""

    __tablename__ = "snapshot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    total: Mapped[Decimal] = mapped_column(Dec)
    liquid: Mapped[Decimal] = mapped_column(Dec)
    hold: Mapped[Decimal] = mapped_column(Dec)
    stake: Mapped[Decimal] = mapped_column(Dec)
    manual: Mapped[Decimal] = mapped_column(Dec)
    n_wallets: Mapped[int] = mapped_column(Integer)
    n_errors: Mapped[int] = mapped_column(Integer, default=0)
    n_unpriced: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict | None] = mapped_column(JsonText, nullable=True)


class HoldTxRow(Base):
    """Mouvement saisi pour le prix de revient (achat hors Hyperliquid, vente, frais)."""

    __tablename__ = "hold_tx"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crypto: Mapped[str] = mapped_column(String(30), index=True)
    time_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    side: Mapped[str] = mapped_column(String(4))  # BUY, SELL, FEE
    qty: Mapped[Decimal] = mapped_column(Dec)
    price: Mapped[Decimal] = mapped_column(Dec)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ManualStakeRow(Base):
    __tablename__ = "manual_stake"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crypto: Mapped[str] = mapped_column(String(30), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    mode: Mapped[str] = mapped_column(String(10), default="apr")  # apr, rewards
    compound_days: Mapped[int] = mapped_column(Integer, default=1)
    reward_dow: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reward_dom: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rewards_restake: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_pct: Mapped[Decimal] = mapped_column(Dec, default=Decimal(0))
    platform_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ManualStakeRateRow(Base):
    __tablename__ = "manual_stake_rate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("manual_stake.id", ondelete="CASCADE"), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    apr_pct: Mapped[Decimal] = mapped_column(Dec)


class ManualStakeTxRow(Base):
    __tablename__ = "manual_stake_tx"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("manual_stake.id", ondelete="CASCADE"), index=True)
    time_ms: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(8))  # STAKE, UNSTAKE, REWARD
    qty: Mapped[Decimal] = mapped_column(Dec)
    effective_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ManualTradeRow(Base):
    __tablename__ = "manual_trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crypto: Mapped[str] = mapped_column(String(30), index=True)
    platform: Mapped[str | None] = mapped_column(String(60), nullable=True)
    direction: Mapped[str] = mapped_column(String(5), default="LONG")
    leverage: Mapped[Decimal] = mapped_column(Dec, default=Decimal(1))
    pnl_override: Mapped[Decimal | None] = mapped_column(Dec, nullable=True)
    open_ms: Mapped[int] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ManualTradeTxRow(Base):
    __tablename__ = "manual_trade_tx"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("manual_trade.id", ondelete="CASCADE"), index=True)
    time_ms: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(8))  # OPEN, ADD, REDUCE
    qty: Mapped[Decimal] = mapped_column(Dec)
    price: Mapped[Decimal] = mapped_column(Dec)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PriceCache(Base):
    """Dernier prix connu par actif (repli quand aucune source ne répond)."""

    __tablename__ = "price_cache"
    base: Mapped[str] = mapped_column(String(30), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Dec)
    source: Mapped[str] = mapped_column(String(40), default="")
    updated_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class KV(Base):
    """Réglages et données de marché simples (paires spot Hyperliquid…)."""

    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JsonText)


class SyncRun(Base):
    __tablename__ = "sync_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    finished_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="running")  # ok, error, running
    n_ok: Mapped[int] = mapped_column(Integer, default=0)
    n_errors: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
