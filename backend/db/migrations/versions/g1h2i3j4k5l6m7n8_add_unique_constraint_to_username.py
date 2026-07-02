"""add unique constraint to username

Revision ID: g1h2i3j4k5l6m7n8
Revises: f6a7b8c9d0e1
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "g1h2i3j4k5l6m7n8"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_index("ix_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_constraint("uq_users_username", "users", type_="unique")
