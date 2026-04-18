"""Slice 4: inventory, orders

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("location_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_no", sa.String(32), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="CREATED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
    )

    op.create_table(
        "order_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_cents", sa.Integer, nullable=False),
    )

    op.create_table(
        "inbound_docs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False, unique=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "inbound_doc_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inbound_docs.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("lot_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "inventory_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("on_hand_qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reserved_qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sellable_qty", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("warehouse_id", "sku_id", name="uq_inventory_balance_warehouse_sku"),
        sa.CheckConstraint("on_hand_qty >= 0", name="ck_inventory_balance_on_hand_qty_non_negative"),
        sa.CheckConstraint("reserved_qty >= 0", name="ck_inventory_balance_reserved_qty_non_negative"),
    )
    op.create_index("ix_inventory_balances_warehouse_sku", "inventory_balances", ["warehouse_id", "sku_id"])

    op.create_table(
        "inventory_lots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("lot_code", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quantity_received", sa.Integer, nullable=False),
        sa.Column("quantity_remaining", sa.Integer, nullable=False),
        sa.Column("source_inbound_doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inbound_docs.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
    )
    op.create_index("ix_inventory_lots_warehouse_sku", "inventory_lots", ["warehouse_id", "sku_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
        sa.Column("movement_type", sa.String(30), nullable=False),
        sa.Column("quantity_delta", sa.Integer, nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=False),
        sa.Column("reference_id", sa.String(100), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "outbound_docs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_no", sa.String(32), nullable=False, unique=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("linked_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "outbound_doc_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("doc_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("outbound_docs.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("inventory_lots.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "stocktakes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "stocktake_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("stocktake_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stocktakes.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("expected_qty", sa.Integer, nullable=False),
        sa.Column("counted_qty", sa.Integer, nullable=False),
        sa.Column("variance_qty", sa.Integer, nullable=False),
        sa.Column("variance_reason", sa.String(30), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
    )

    op.create_table(
        "reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reservation_no", sa.String(32), nullable=False, unique=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("order_id", "idempotency_key", name="uq_reservation_order_idempotency"),
    )

    op.create_table(
        "reorder_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("sellable_qty", sa.Integer, nullable=False),
        sa.Column("threshold", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("reorder_alerts")
    op.drop_table("reservations")
    op.drop_table("stocktake_lines")
    op.drop_table("stocktakes")
    op.drop_table("outbound_doc_lines")
    op.drop_table("outbound_docs")
    op.drop_table("inventory_movements")
    op.drop_index("ix_inventory_lots_warehouse_sku", table_name="inventory_lots")
    op.drop_table("inventory_lots")
    op.drop_index("ix_inventory_balances_warehouse_sku", table_name="inventory_balances")
    op.drop_table("inventory_balances")
    op.drop_table("inbound_doc_lines")
    op.drop_table("inbound_docs")
    op.drop_table("order_lines")
    op.drop_table("orders")
    op.drop_table("warehouses")
