"""add daily predictions table

Revision ID: abc123
Revises: 9a6d4c1b2ef0
Create Date: 2026-03-30 19:45:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "abc123"
down_revision = "9a6d4c1b2ef0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_predictions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("symbol", sa.String(length=12), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("conviction_score", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("thesis_summary", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("invalidation_conditions", sa.Text(), nullable=False),
        sa.Column("horizon_ranges", sa.JSON(), nullable=False),
        sa.Column("factor_scores", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("news_snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recommendation_snapshot_id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "symbol", name="uq_daily_predictions_date_symbol"),
    )
    op.create_index("ix_daily_predictions_date", "daily_predictions", ["date"])
    op.create_index("ix_daily_predictions_symbol", "daily_predictions", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_daily_predictions_symbol", table_name="daily_predictions")
    op.drop_index("ix_daily_predictions_date", table_name="daily_predictions")
    op.drop_table("daily_predictions")
