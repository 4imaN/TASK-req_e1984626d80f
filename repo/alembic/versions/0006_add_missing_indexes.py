"""Add missing prompt-required indexes

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_items_id_status", "items", ["id", "status"])
    op.create_index("ix_reviews_user_created", "reviews", ["user_id", "created_at"])
    op.create_index("ix_reviews_item_status", "reviews", ["item_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_reviews_item_status", table_name="reviews")
    op.drop_index("ix_reviews_user_created", table_name="reviews")
    op.drop_index("ix_items_id_status", table_name="items")
