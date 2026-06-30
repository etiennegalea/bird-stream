"""drop gdpr_ip_consent from users

Revision ID: a9b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a9b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('users', 'gdpr_ip_consent')


def downgrade() -> None:
    op.add_column(
        'users',
        sa.Column('gdpr_ip_consent', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
