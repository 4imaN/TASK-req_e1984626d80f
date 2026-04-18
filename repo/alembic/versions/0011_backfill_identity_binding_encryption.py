"""Backfill identity_binding encryption for legacy rows

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-18
"""
import hashlib
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, institution_code, binding_type, external_id FROM identity_bindings WHERE external_id_encrypted IS NULL")
    ).fetchall()

    if not rows:
        return

    key_hex = os.environ.get("ENCRYPTION_MASTER_KEY")
    if not key_hex:
        key_file = os.environ.get("ENCRYPTION_MASTER_KEY_FILE", "/run/secrets/master.key")
        if os.path.exists(key_file):
            raw = open(key_file).read().strip()
            key_hex = raw
        else:
            return

    if len(key_hex) == 64:
        key = bytes.fromhex(key_hex)
    elif len(key_hex) == 32:
        key = key_hex.encode()
    else:
        return

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os as _os

    for row in rows:
        rid, inst_code, btype, ext_id = row
        nonce = _os.urandom(12)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, ext_id.encode("utf-8"), None)
        version_byte = (1).to_bytes(1, "big")
        encrypted_hex = (version_byte + nonce + ct).hex()

        ext_id_hash = hashlib.sha256(f"{inst_code}:{btype}:{ext_id}".encode()).hexdigest()[:100]

        conn.execute(
            sa.text(
                "UPDATE identity_bindings SET external_id_encrypted = :enc, external_id = :hash WHERE id = :id"
            ),
            {"enc": encrypted_hex, "hash": ext_id_hash, "id": rid},
        )


def downgrade() -> None:
    pass
