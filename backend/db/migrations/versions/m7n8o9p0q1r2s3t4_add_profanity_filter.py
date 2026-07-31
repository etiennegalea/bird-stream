"""add profanity preference and rolling occurrence records

Revision ID: m7n8o9p0q1r2s3t4
Revises: l6m7n8o9p0q1r2s3
"""

import sqlalchemy as sa
from alembic import op

revision = "m7n8o9p0q1r2s3t4"
down_revision = "l6m7n8o9p0q1r2s3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("profanity_filter_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_table(
        "profanity_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profanity_occurrences_user_occurred",
        "profanity_occurrences",
        ["user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_profanity_occurrences_user_occurred", table_name="profanity_occurrences")
    op.drop_table("profanity_occurrences")
    op.drop_column("users", "profanity_filter_enabled")
