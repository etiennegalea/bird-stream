"""add per-device POV camera automation

Revision ID: n8o9p0q1r2s3t4u5
Revises: m7n8o9p0q1r2s3t4
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n8o9p0q1r2s3t4u5"
down_revision: Union[str, Sequence[str], None] = "m7n8o9p0q1r2s3t4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_camera_automation",
        sa.Column("pi_id", sa.String(length=64), nullable=False),
        sa.Column(
            "auto_manage_pov", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "bird_triggered_pov", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("pi_id"),
    )


def downgrade() -> None:
    op.drop_table("device_camera_automation")
