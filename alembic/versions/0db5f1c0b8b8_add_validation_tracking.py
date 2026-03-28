"""add validation tracking

Revision ID: 0db5f1c0b8b8
Revises: 7014147e9da6
Create Date: 2026-03-27 14:35:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0db5f1c0b8b8"
down_revision = "7014147e9da6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendation_snapshots",
        sa.Column("reference_price", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "recommendation_snapshots",
        sa.Column("benchmark_reference_price", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE recommendation_snapshots
        SET reference_price = COALESCE(
            (SELECT securities.last_price FROM securities WHERE securities.id = recommendation_snapshots.security_id),
            0
        )
        """
    )
    op.execute("UPDATE recommendation_snapshots SET benchmark_reference_price = 488.12")

    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recommendation_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("security_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reference_price", sa.Float(), nullable=False),
        sa.Column("benchmark_reference_price", sa.Float(), nullable=False),
        sa.Column("observed_price", sa.Float(), nullable=True),
        sa.Column("benchmark_observed_price", sa.Float(), nullable=True),
        sa.Column("observed_return_pct", sa.Float(), nullable=True),
        sa.Column("strategy_return_pct", sa.Float(), nullable=True),
        sa.Column("benchmark_return_pct", sa.Float(), nullable=True),
        sa.Column("excess_return_pct", sa.Float(), nullable=True),
        sa.Column("baseline_label", sa.String(length=32), nullable=False),
        sa.Column("baseline_action", sa.String(length=12), nullable=False),
        sa.Column("baseline_return_pct", sa.Float(), nullable=True),
        sa.Column("directional_correct", sa.Boolean(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_snapshot_id"], ["recommendation_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_snapshot_id", "horizon_days", name="uq_recommendation_outcome_horizon"),
    )
    op.create_index("ix_recommendation_outcomes_status", "recommendation_outcomes", ["status"], unique=False)
    op.create_index("ix_recommendation_outcomes_target_at", "recommendation_outcomes", ["target_at"], unique=False)
    op.create_index("ix_recommendation_outcomes_security_id", "recommendation_outcomes", ["security_id"], unique=False)

    op.create_table(
        "validation_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("report_date", sa.String(length=10), nullable=False),
        sa.Column("benchmark_symbol", sa.String(length=12), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funnel_json", sa.JSON(), nullable=False),
        sa.Column("forecast_metrics_json", sa.JSON(), nullable=False),
        sa.Column("shadow_portfolio_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_date", name="uq_validation_reports_report_date"),
    )
    op.create_index("ix_validation_reports_generated_at", "validation_reports", ["generated_at"], unique=False)

def downgrade() -> None:
    op.drop_index("ix_validation_reports_generated_at", table_name="validation_reports")
    op.drop_table("validation_reports")

    op.drop_index("ix_recommendation_outcomes_security_id", table_name="recommendation_outcomes")
    op.drop_index("ix_recommendation_outcomes_target_at", table_name="recommendation_outcomes")
    op.drop_index("ix_recommendation_outcomes_status", table_name="recommendation_outcomes")
    op.drop_table("recommendation_outcomes")

    op.drop_column("recommendation_snapshots", "benchmark_reference_price")
    op.drop_column("recommendation_snapshots", "reference_price")
