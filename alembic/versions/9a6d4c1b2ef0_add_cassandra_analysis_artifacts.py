"""add cassandra analysis artifacts

Revision ID: 9a6d4c1b2ef0
Revises: 0db5f1c0b8b8
Create Date: 2026-03-29 12:20:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9a6d4c1b2ef0"
down_revision = "0db5f1c0b8b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendation_snapshots",
        sa.Column("analysis_artifacts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("recommendation_snapshots", "analysis_artifacts")
