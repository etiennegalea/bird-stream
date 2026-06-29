"""add updated_at to all tables

Revision ID: b7e2a9c4f015
Revises: a3f1d8c2e904
Create Date: 2026-06-28 13:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2a9c4f015"
down_revision: Union[str, Sequence[str], None] = "a3f1d8c2e904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ["users", "auth_tokens", "chat_messages", "bird_detections"]


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "updated_at")
