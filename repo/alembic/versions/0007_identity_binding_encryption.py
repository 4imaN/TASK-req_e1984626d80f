"""Add external_id_encrypted to identity_bindings

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("identity_bindings", sa.Column("external_id_encrypted", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("identity_bindings", "external_id_encrypted")
