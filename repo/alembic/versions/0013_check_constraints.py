"""Add CHECK constraints for rating range and share link download counts

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_review_rating_range",
        "reviews",
        "rating >= 1 AND rating <= 5",
    )
    op.create_check_constraint(
        "ck_share_link_download_count",
        "share_links",
        "download_count >= 0",
    )
    op.create_check_constraint(
        "ck_share_link_max_downloads",
        "share_links",
        "max_downloads >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_rating_range", "reviews", type_="check")
    op.drop_constraint("ck_share_link_download_count", "share_links", type_="check")
    op.drop_constraint("ck_share_link_max_downloads", "share_links", type_="check")
