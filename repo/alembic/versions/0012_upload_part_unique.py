"""Add unique constraint on upload_parts (upload_session_id, part_number)

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_upload_part_session_partno",
        "upload_parts",
        ["upload_session_id", "part_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_upload_part_session_partno", "upload_parts", type_="unique")
