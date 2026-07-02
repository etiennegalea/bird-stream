"""add is_admin to users

Revision ID: h2i3j4k5l6m7n8o9
Revises: g1h2i3j4k5l6m7n8
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "h2i3j4k5l6m7n8o9"
down_revision: Union[str, Sequence[str], None] = "g1h2i3j4k5l6m7n8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
