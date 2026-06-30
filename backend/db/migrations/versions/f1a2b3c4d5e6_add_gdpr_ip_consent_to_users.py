"""add gdpr_ip_consent and last_ip to users

Revision ID: f1a2b3c4d5e6
Revises: d4e8f1c2a63b
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'd4e8f1c2a63b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('gdpr_ip_consent', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('users', sa.Column('last_ip', sa.String(45), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_ip')
    op.drop_column('users', 'gdpr_ip_consent')
