"""add avatar and bio to users

Revision ID: d4e8f1c2a63b
Revises: b7e2a9c4f015
Create Date: 2026-06-30 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e8f1c2a63b'
down_revision = 'b7e2a9c4f015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('avatar', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('bio', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'bio')
    op.drop_column('users', 'avatar')
