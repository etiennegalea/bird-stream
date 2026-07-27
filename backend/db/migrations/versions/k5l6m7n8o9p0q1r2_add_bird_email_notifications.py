"""add bird email notification preference

Revision ID: k5l6m7n8o9p0q1r2
Revises: j4k5l6m7n8o9p0q1
"""

import sqlalchemy as sa
from alembic import op

revision = "k5l6m7n8o9p0q1r2"
down_revision = "j4k5l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "bird_notification_email",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "bird_notification_email")
