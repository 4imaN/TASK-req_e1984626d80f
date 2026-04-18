"""Slice 5: reviews, moderation

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sensitive_word_terms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("term", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("dictionary_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("body_raw", sa.Text, nullable=False),
        sa.Column("body_public", sa.Text, nullable=True),
        sa.Column("structured_tags_json", sa.Text, nullable=True),
        sa.Column("latest_revision_no", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reviews_item_id", "reviews", ["item_id"])
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"])

    op.create_table(
        "review_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("body_raw", sa.Text, nullable=False),
        sa.Column("body_public", sa.Text, nullable=True),
        sa.Column("structured_tags_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_review_revisions_review_id", "review_revisions", ["review_id"])

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason_code", sa.String(50), nullable=False),
        sa.Column("details_raw", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="SUBMITTED"),
        sa.Column("triage_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reports_reporter_user_id", "reports", ["reporter_user_id"])
    op.create_index("ix_reports_status", "reports", ["status"])

    op.create_table(
        "report_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("private_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_report_events_report_id", "report_events", ["report_id"])

    op.create_table(
        "appeals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id"), nullable=True),
        sa.Column("appellant_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="SUBMITTED"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_appeals_appellant_user_id", "appeals", ["appellant_user_id"])
    op.create_index("ix_appeals_report_id", "appeals", ["report_id"])
    op.create_index("ix_appeals_review_id", "appeals", ["review_id"])

    op.create_table(
        "appeal_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("appeal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("appeals.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_appeal_events_appeal_id", "appeal_events", ["appeal_id"])


def downgrade() -> None:
    op.drop_index("ix_appeal_events_appeal_id", table_name="appeal_events")
    op.drop_table("appeal_events")
    op.drop_index("ix_appeals_review_id", table_name="appeals")
    op.drop_index("ix_appeals_report_id", table_name="appeals")
    op.drop_index("ix_appeals_appellant_user_id", table_name="appeals")
    op.drop_table("appeals")
    op.drop_index("ix_report_events_report_id", table_name="report_events")
    op.drop_table("report_events")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_reporter_user_id", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_review_revisions_review_id", table_name="review_revisions")
    op.drop_table("review_revisions")
    op.drop_index("ix_reviews_user_id", table_name="reviews")
    op.drop_index("ix_reviews_item_id", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("sensitive_word_terms")
