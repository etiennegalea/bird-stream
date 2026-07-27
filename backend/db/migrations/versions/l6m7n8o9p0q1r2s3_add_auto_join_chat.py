"""add auto-join chat preference

Revision ID: l6m7n8o9p0q1r2s3
Revises: k5l6m7n8o9p0q1r2
"""

import sqlalchemy as sa
from alembic import op

revision = "l6m7n8o9p0q1r2s3"
down_revision = "k5l6m7n8o9p0q1r2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "auto_join_chat",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "auto_join_chat")
