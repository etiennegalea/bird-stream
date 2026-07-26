"""add persisted stream configuration

Revision ID: i3j4k5l6m7n8o9p0
Revises: h2i3j4k5l6m7n8o9
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8o9p0"
down_revision: Union[str, Sequence[str], None] = "h2i3j4k5l6m7n8o9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stream_configuration",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "private_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "stream_configuration",
            sa.column("id", sa.Integer()),
            sa.column("private_enabled", sa.Boolean()),
        ),
        [{"id": 1, "private_enabled": False}],
    )


def downgrade() -> None:
    op.drop_table("stream_configuration")
