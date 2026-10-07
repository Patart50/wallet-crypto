"""Schéma initial (v1.0) : celui des bases créées par les versions 0.x.

Montants en texte décimal exact (``DecimalText`` côté modèle, ``String(80)`` ici), JSON en texte.
Les migrations ne dépendent pas des classes du modèle : elles décrivent le stockage.

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hl_fill",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=64), nullable=False),
        sa.Column("tid", sa.BigInteger(), nullable=False),
        sa.Column("oid", sa.BigInteger(), nullable=True),
        sa.Column("coin", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=2), nullable=False),
        sa.Column("px", sa.String(length=80), nullable=False),
        sa.Column("sz", sa.String(length=80), nullable=False),
        sa.Column("dir", sa.String(length=40), nullable=True),
        sa.Column("start_position", sa.String(length=80), nullable=False),
        sa.Column("closed_pnl", sa.String(length=80), nullable=False),
        sa.Column("fee", sa.String(length=80), nullable=False),
        sa.Column("fee_token", sa.String(length=12), nullable=True),
        sa.Column("builder_fee", sa.String(length=80), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.String(length=80), nullable=True),
        sa.Column("crossed", sa.Boolean(), nullable=True),
        sa.Column("liquidation", sa.Boolean(), nullable=False),
        sa.Column("is_spot", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "tid", name="uq_hl_fill_address_tid"),
    )
    op.create_index(op.f("ix_hl_fill_address"), "hl_fill", ["address"], unique=False)
    op.create_index(op.f("ix_hl_fill_coin"), "hl_fill", ["coin"], unique=False)
    op.create_index(op.f("ix_hl_fill_is_spot"), "hl_fill", ["is_spot"], unique=False)
    op.create_index(op.f("ix_hl_fill_time_ms"), "hl_fill", ["time_ms"], unique=False)
    op.create_table(
        "hl_funding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("address", sa.String(length=64), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("coin", sa.String(length=30), nullable=False),
        sa.Column("usdc", sa.String(length=80), nullable=False),
        sa.Column("szi", sa.String(length=80), nullable=True),
        sa.Column("rate", sa.String(length=80), nullable=True),
        sa.Column("hash", sa.String(length=80), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "time_ms", "coin", name="uq_hl_funding"),
    )
    op.create_index(op.f("ix_hl_funding_address"), "hl_funding", ["address"], unique=False)
    op.create_index(op.f("ix_hl_funding_time_ms"), "hl_funding", ["time_ms"], unique=False)
    op.create_table(
        "hold_tx",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crypto", sa.String(length=30), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("side", sa.String(length=4), nullable=False),
        sa.Column("qty", sa.String(length=80), nullable=False),
        sa.Column("price", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hold_tx_crypto"), "hold_tx", ["crypto"], unique=False)
    op.create_index(op.f("ix_hold_tx_time_ms"), "hold_tx", ["time_ms"], unique=False)
    op.create_table(
        "kline_cache",
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("day_ms", sa.BigInteger(), nullable=False),
        sa.Column("close", sa.String(length=80), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "day_ms"),
    )
    op.create_table(
        "kv",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "manual_stake",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crypto", sa.String(length=30), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("compound_days", sa.Integer(), nullable=False),
        sa.Column("reward_dow", sa.Integer(), nullable=True),
        sa.Column("reward_dom", sa.Integer(), nullable=True),
        sa.Column("rewards_restake", sa.Boolean(), nullable=False),
        sa.Column("fee_pct", sa.String(length=80), nullable=False),
        sa.Column("platform_url", sa.String(length=300), nullable=True),
        sa.Column("entry_price", sa.String(length=80), nullable=True),
        sa.Column("end_ms", sa.BigInteger(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_manual_stake_crypto"), "manual_stake", ["crypto"], unique=False)
    op.create_table(
        "manual_trade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crypto", sa.String(length=30), nullable=False),
        sa.Column("platform", sa.String(length=60), nullable=True),
        sa.Column("direction", sa.String(length=5), nullable=False),
        sa.Column("leverage", sa.String(length=80), nullable=False),
        sa.Column("pnl_override", sa.String(length=80), nullable=True),
        sa.Column("open_ms", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_manual_trade_crypto"), "manual_trade", ["crypto"], unique=False)
    op.create_table(
        "price_cache",
        sa.Column("base", sa.String(length=30), nullable=False),
        sa.Column("price", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("updated_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("base"),
    )
    op.create_table(
        "snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts_ms", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.String(length=80), nullable=False),
        sa.Column("liquid", sa.String(length=80), nullable=False),
        sa.Column("hold", sa.String(length=80), nullable=False),
        sa.Column("stake", sa.String(length=80), nullable=False),
        sa.Column("manual", sa.String(length=80), nullable=False),
        sa.Column("n_wallets", sa.Integer(), nullable=False),
        sa.Column("n_errors", sa.Integer(), nullable=False),
        sa.Column("n_unpriced", sa.Integer(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_snapshot_ts_ms"), "snapshot", ["ts_ms"], unique=False)
    op.create_table(
        "stake_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("address", sa.String(length=64), nullable=False),
        sa.Column("asset", sa.String(length=20), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("qty", sa.String(length=80), nullable=False),
        sa.Column("hash", sa.String(length=80), nullable=True),
        sa.Column("ext_id", sa.String(length=190), nullable=False),
        sa.Column("detail", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ext_id", name="uq_stake_event_ext_id"),
    )
    op.create_index(op.f("ix_stake_event_address"), "stake_event", ["address"], unique=False)
    op.create_index(op.f("ix_stake_event_source"), "stake_event", ["source"], unique=False)
    op.create_index(op.f("ix_stake_event_time_ms"), "stake_event", ["time_ms"], unique=False)
    op.create_table(
        "sync_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_ms", sa.BigInteger(), nullable=False),
        sa.Column("finished_ms", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("n_ok", sa.Integer(), nullable=False),
        sa.Column("n_errors", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sync_run_started_ms"), "sync_run", ["started_ms"], unique=False)
    op.create_table(
        "wallet",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_name", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("network", sa.String(length=10), nullable=False),
        sa.Column("address", sa.String(length=100), nullable=False),
        sa.Column("track_staking", sa.Boolean(), nullable=False),
        sa.Column("auto_trading", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_sync_ms", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_ms", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address", "network", name="uq_wallet_address_network"),
    )
    op.create_index(op.f("ix_wallet_address"), "wallet", ["address"], unique=False)
    op.create_table(
        "balance_line",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("coin", sa.String(length=40), nullable=False),
        sa.Column("qty", sa.String(length=80), nullable=False),
        sa.Column("val", sa.String(length=80), nullable=True),
        sa.Column("src", sa.String(length=30), nullable=False),
        sa.Column("px_sync", sa.String(length=80), nullable=True),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column("synced_ms", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallet.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "coin", name="uq_balance_wallet_coin"),
    )
    op.create_index(op.f("ix_balance_line_wallet_id"), "balance_line", ["wallet_id"], unique=False)
    op.create_table(
        "hl_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("coin", sa.String(length=30), nullable=False),
        sa.Column("side", sa.String(length=5), nullable=False),
        sa.Column("size", sa.String(length=80), nullable=False),
        sa.Column("entry", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=80), nullable=False),
        sa.Column("upnl", sa.String(length=80), nullable=False),
        sa.Column("lev", sa.String(length=80), nullable=True),
        sa.Column("liq_px", sa.String(length=80), nullable=True),
        sa.Column("roe", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallet.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hl_position_wallet_id"), "hl_position", ["wallet_id"], unique=False)
    op.create_table(
        "manual_stake_rate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=True),
        sa.Column("apr_pct", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["manual_stake.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_manual_stake_rate_position_id"), "manual_stake_rate", ["position_id"], unique=False
    )
    op.create_table(
        "manual_stake_tx",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.String(length=80), nullable=False),
        sa.Column("effective_ms", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["position_id"], ["manual_stake.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_manual_stake_tx_position_id"), "manual_stake_tx", ["position_id"], unique=False)
    op.create_table(
        "manual_trade_tx",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("time_ms", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("qty", sa.String(length=80), nullable=False),
        sa.Column("price", sa.String(length=80), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["trade_id"], ["manual_trade.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_manual_trade_tx_trade_id"), "manual_trade_tx", ["trade_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_manual_trade_tx_trade_id"), table_name="manual_trade_tx")
    op.drop_table("manual_trade_tx")
    op.drop_index(op.f("ix_manual_stake_tx_position_id"), table_name="manual_stake_tx")
    op.drop_table("manual_stake_tx")
    op.drop_index(op.f("ix_manual_stake_rate_position_id"), table_name="manual_stake_rate")
    op.drop_table("manual_stake_rate")
    op.drop_index(op.f("ix_hl_position_wallet_id"), table_name="hl_position")
    op.drop_table("hl_position")
    op.drop_index(op.f("ix_balance_line_wallet_id"), table_name="balance_line")
    op.drop_table("balance_line")
    op.drop_index(op.f("ix_wallet_address"), table_name="wallet")
    op.drop_table("wallet")
    op.drop_index(op.f("ix_sync_run_started_ms"), table_name="sync_run")
    op.drop_table("sync_run")
    op.drop_index(op.f("ix_stake_event_time_ms"), table_name="stake_event")
    op.drop_index(op.f("ix_stake_event_source"), table_name="stake_event")
    op.drop_index(op.f("ix_stake_event_address"), table_name="stake_event")
    op.drop_table("stake_event")
    op.drop_index(op.f("ix_snapshot_ts_ms"), table_name="snapshot")
    op.drop_table("snapshot")
    op.drop_table("price_cache")
    op.drop_index(op.f("ix_manual_trade_crypto"), table_name="manual_trade")
    op.drop_table("manual_trade")
    op.drop_index(op.f("ix_manual_stake_crypto"), table_name="manual_stake")
    op.drop_table("manual_stake")
    op.drop_table("kv")
    op.drop_table("kline_cache")
    op.drop_index(op.f("ix_hold_tx_time_ms"), table_name="hold_tx")
    op.drop_index(op.f("ix_hold_tx_crypto"), table_name="hold_tx")
    op.drop_table("hold_tx")
    op.drop_index(op.f("ix_hl_funding_time_ms"), table_name="hl_funding")
    op.drop_index(op.f("ix_hl_funding_address"), table_name="hl_funding")
    op.drop_table("hl_funding")
    op.drop_index(op.f("ix_hl_fill_time_ms"), table_name="hl_fill")
    op.drop_index(op.f("ix_hl_fill_is_spot"), table_name="hl_fill")
    op.drop_index(op.f("ix_hl_fill_coin"), table_name="hl_fill")
    op.drop_index(op.f("ix_hl_fill_address"), table_name="hl_fill")
    op.drop_table("hl_fill")
