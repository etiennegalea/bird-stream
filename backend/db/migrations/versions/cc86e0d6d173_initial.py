"""initial

Revision ID: cc86e0d6d173
Revises:
Create Date: 2026-06-14 09:27:22.088242

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'cc86e0d6d173'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(20), nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("message_type", sa.String(20), nullable=False, server_default="message"),
    )
    op.create_table(
        "bird_detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("species", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bird_detections")
    op.drop_table("chat_messages")
