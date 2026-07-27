"""add is_blocked to users

Revision ID: j4k5l6m7n8o9p0q1
Revises: i3j4k5l6m7n8o9p0
"""

import sqlalchemy as sa
from alembic import op

revision = "j4k5l6m7n8o9p0q1"
down_revision = "i3j4k5l6m7n8o9p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_blocked")
