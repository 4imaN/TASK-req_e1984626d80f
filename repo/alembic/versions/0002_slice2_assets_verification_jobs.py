"""Slice 2: assets, verification, share links, jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_blobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("is_encrypted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("thumbnail_path", sa.String(500), nullable=True),
        sa.Column("metadata_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asset_blobs_hash", "asset_blobs", ["asset_hash"])

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blob_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("asset_blobs.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("asset_hash", sa.String(64), nullable=False),
        sa.Column("watermark_policy", sa.String(20), nullable=False, server_default="NONE"),
        sa.Column("purpose", sa.String(30), nullable=False, server_default="GENERAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "upload_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("total_size", sa.Integer, nullable=False),
        sa.Column("total_parts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("kind", sa.String(30), nullable=False, server_default="IMAGE"),
        sa.Column("purpose", sa.String(30), nullable=False, server_default="GENERAL"),
        sa.Column("status", sa.String(20), nullable=False, server_default="INITIATED"),
        sa.Column("received_parts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("received_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("storage_temp_dir", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "upload_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("upload_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("upload_sessions.id"), nullable=False),
        sa.Column("part_number", sa.Integer, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "share_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("token", sa.String(128), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_downloads", sa.Integer, nullable=False, server_default="20"),
        sa.Column("download_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "share_link_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("share_link_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("share_links.id"), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("failure_reason", sa.String(100), nullable=True),
    )

    op.create_table(
        "verification_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(32), nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("profile_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("legal_name_encrypted", sa.Text, nullable=True),
        sa.Column("dob_encrypted", sa.Text, nullable=True),
        sa.Column("government_id_number_encrypted", sa.Text, nullable=True),
        sa.Column("government_id_image_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("enterprise_legal_name_encrypted", sa.Text, nullable=True),
        sa.Column("enterprise_registration_number_encrypted", sa.Text, nullable=True),
        sa.Column("enterprise_registration_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("responsible_person_legal_name_encrypted", sa.Text, nullable=True),
        sa.Column("responsible_person_dob_encrypted", sa.Text, nullable=True),
        sa.Column("responsible_person_id_number_encrypted", sa.Text, nullable=True),
        sa.Column("responsible_person_id_image_asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("row_version", sa.Integer, nullable=False, server_default="1"),
    )

    op.create_table(
        "verification_case_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("verification_cases.id"), nullable=False),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "verification_case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("verification_cases.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("response_json", sa.Text, nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("jobs")
    op.drop_table("verification_case_events")
    op.drop_table("verification_case_revisions")
    op.drop_table("verification_cases")
    op.drop_table("share_link_access_logs")
    op.drop_table("share_links")
    op.drop_table("upload_parts")
    op.drop_table("upload_sessions")
    op.drop_table("assets")
    op.drop_index("ix_asset_blobs_hash", table_name="asset_blobs")
    op.drop_table("asset_blobs")
