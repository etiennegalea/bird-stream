"""add sender_type to chat_messages

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'chat_messages',
        sa.Column(
            'sender_type',
            sa.String(10),
            nullable=False,
            server_default='guest',
        ),
    )


def downgrade() -> None:
    op.drop_column('chat_messages', 'sender_type')
