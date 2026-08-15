"""add chat soft deletion and admin action audit

Revision ID: o9p0q1r2s3t4u5v6
Revises: n8o9p0q1r2s3t4u5
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o9p0q1r2s3t4u5v6"
down_revision: Union[str, Sequence[str], None] = "n8o9p0q1r2s3t4u5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "chat_messages",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "chat_messages",
        sa.Column("deleted_by_admin_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_chat_messages_deleted_by_admin_id_users",
        "chat_messages", "users", ["deleted_by_admin_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_actions_created_at", "admin_actions", ["created_at"])
    op.create_index("ix_admin_actions_action_type", "admin_actions", ["action_type"])


def downgrade() -> None:
    op.drop_index("ix_admin_actions_action_type", table_name="admin_actions")
    op.drop_index("ix_admin_actions_created_at", table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_constraint(
        "fk_chat_messages_deleted_by_admin_id_users",
        "chat_messages",
        type_="foreignkey",
    )
    op.drop_column("chat_messages", "deleted_by_admin_id")
    op.drop_column("chat_messages", "deleted_at")
    op.drop_column("chat_messages", "is_deleted")
