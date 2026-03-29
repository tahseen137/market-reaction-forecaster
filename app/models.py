from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base


def _timestamp() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp, onupdate=_timestamp)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_role", "role"),
        Index("ix_users_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(24), default="trial_user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verification_token: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_reset_token: Mapped[str | None] = mapped_column(String(120), nullable=True)
    disclosures_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["UserProfile | None"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    subscription_state: Mapped["SubscriptionState | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    watchlists: Mapped[list["Watchlist"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    personalized_recommendations: Mapped[list["UserRecommendation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    portfolio_positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    activity_events: Mapped[list["ActivityEvent"]] = relationship(back_populates="actor")


class UserProfile(TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_profiles_user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    age_band: Mapped[str] = mapped_column(String(32), nullable=False)
    investable_amount_band: Mapped[str] = mapped_column(String(32), nullable=False)
    goal_primary: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_tolerance: Mapped[str] = mapped_column(String(24), nullable=False)
    max_drawdown_band: Mapped[str] = mapped_column(String(24), nullable=False)
    holding_period_preference: Mapped[str] = mapped_column(String(32), nullable=False)
    income_stability_band: Mapped[str] = mapped_column(String(24), nullable=False)
    sector_concentration_tolerance: Mapped[str] = mapped_column(String(24), nullable=False)
    experience_level: Mapped[str] = mapped_column(String(24), nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class SubscriptionState(TimestampMixin, Base):
    __tablename__ = "subscription_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscription_states_user_id"),
        Index("ix_subscription_states_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_key: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="free", nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_webhook_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped[User] = relationship(back_populates="subscription_state")


class Security(TimestampMixin, Base):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_securities_symbol"),
        Index("ix_securities_is_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(12), nullable=False)
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    sector: Mapped[str] = mapped_column(String(60), nullable=False)
    exchange: Mapped[str] = mapped_column(String(24), default="NASDAQ", nullable=False)
    cik: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    day_change_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["Event"]] = relationship(back_populates="security", cascade="all, delete-orphan")
    recommendation_snapshots: Mapped[list["RecommendationSnapshot"]] = relationship(
        back_populates="security",
        cascade="all, delete-orphan",
    )
    watchlist_links: Mapped[list["WatchlistSecurity"]] = relationship(back_populates="security", cascade="all, delete-orphan")
    portfolio_positions: Mapped[list["PortfolioPosition"]] = relationship(back_populates="security")


class Watchlist(TimestampMixin, Base):
    __tablename__ = "watchlists"
    __table_args__ = (Index("ix_watchlists_user_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)

    user: Mapped[User] = relationship(back_populates="watchlists")
    securities: Mapped[list["WatchlistSecurity"]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class WatchlistSecurity(Base):
    __tablename__ = "watchlist_securities"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "security_id", name="uq_watchlist_security"),
        Index("ix_watchlist_securities_security_id", "security_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), nullable=False)

    watchlist: Mapped[Watchlist] = relationship(back_populates="securities")
    security: Mapped[Security] = relationship(back_populates="watchlist_links")


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_source_snapshots_content_hash"),
        Index("ix_source_snapshots_published_at", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    headline: Mapped[str] = mapped_column(String(280), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp)

    events: Mapped[list["Event"]] = relationship(back_populates="source_snapshot")


class Event(TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_events_dedupe_key"),
        Index("ix_events_security_id", "security_id"),
        Index("ix_events_occurred_at", "occurred_at"),
        Index("ix_events_event_type", "event_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), nullable=False)
    source_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("source_snapshots.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    headline: Mapped[str] = mapped_column(String(280), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    thesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_label: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    directional_bias: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_material: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    operator_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    security: Mapped[Security] = relationship(back_populates="events")
    source_snapshot: Mapped[SourceSnapshot | None] = relationship(back_populates="events")
    recommendation_snapshots: Mapped[list["RecommendationSnapshot"]] = relationship(back_populates="latest_event")


class RecommendationSnapshot(Base):
    __tablename__ = "recommendation_snapshots"
    __table_args__ = (
        Index("ix_recommendation_snapshots_security_id", "security_id"),
        Index("ix_recommendation_snapshots_generated_at", "generated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), nullable=False)
    latest_event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    model_version: Mapped[str] = mapped_column(String(60), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp, nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    conviction_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    analog_sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(String(12), default="QQQ", nullable=False)
    reference_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    benchmark_reference_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_status: Mapped[str] = mapped_column(String(16), default="delayed", nullable=False)
    thesis_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    invalidation_conditions: Mapped[str] = mapped_column(Text, nullable=False)
    factor_scores: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    horizon_ranges: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)
    analysis_artifacts: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    security: Mapped[Security] = relationship(back_populates="recommendation_snapshots")
    latest_event: Mapped[Event | None] = relationship(back_populates="recommendation_snapshots")
    personalized_recommendations: Mapped[list["UserRecommendation"]] = relationship(
        back_populates="recommendation_snapshot",
        cascade="all, delete-orphan",
    )
    validation_outcomes: Mapped[list["RecommendationOutcome"]] = relationship(
        back_populates="recommendation_snapshot",
        cascade="all, delete-orphan",
    )


class UserRecommendation(Base):
    __tablename__ = "user_recommendations"
    __table_args__ = (
        UniqueConstraint("user_id", "recommendation_snapshot_id", name="uq_user_recommendation_snapshot"),
        Index("ix_user_recommendations_user_id", "user_id"),
        Index("ix_user_recommendations_action", "action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recommendation_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    conviction_score: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_fit_score: Mapped[float] = mapped_column(Float, nullable=False)
    allocation_min_pct: Mapped[float] = mapped_column(Float, nullable=False)
    allocation_max_pct: Mapped[float] = mapped_column(Float, nullable=False)
    urgency_label: Mapped[str] = mapped_column(String(24), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    profile_inputs_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp)

    user: Mapped[User] = relationship(back_populates="personalized_recommendations")
    recommendation_snapshot: Mapped[RecommendationSnapshot] = relationship(back_populates="personalized_recommendations")


class RecommendationOutcome(TimestampMixin, Base):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint("recommendation_snapshot_id", "horizon_days", name="uq_recommendation_outcome_horizon"),
        Index("ix_recommendation_outcomes_status", "status"),
        Index("ix_recommendation_outcomes_target_at", "target_at"),
        Index("ix_recommendation_outcomes_security_id", "security_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    recommendation_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("recommendation_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(String(12), default="QQQ", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    benchmark_reference_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    observed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_observed_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    excess_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_label: Mapped[str] = mapped_column(String(32), default="event_bias", nullable=False)
    baseline_action: Mapped[str] = mapped_column(String(12), default="hold", nullable=False)
    baseline_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    directional_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    recommendation_snapshot: Mapped[RecommendationSnapshot] = relationship(back_populates="validation_outcomes")
    security: Mapped[Security] = relationship()


class ValidationReport(Base):
    __tablename__ = "validation_reports"
    __table_args__ = (
        UniqueConstraint("report_date", name="uq_validation_reports_report_date"),
        Index("ix_validation_reports_generated_at", "generated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    report_date: Mapped[str] = mapped_column(String(10), nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(String(12), default="QQQ", nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp, nullable=False)
    funnel_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    forecast_metrics_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    shadow_portfolio_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (Index("ix_backtest_runs_generated_at", "generated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scope_label: Mapped[str] = mapped_column(String(120), nullable=False)
    benchmark_symbol: Mapped[str] = mapped_column(String(12), default="QQQ", nullable=False)
    universe_version: Mapped[str] = mapped_column(String(24), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_return: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    benchmark_return: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    calibration_error: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


class PortfolioPosition(TimestampMixin, Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        Index("ix_portfolio_positions_user_id", "user_id"),
        Index("ix_portfolio_positions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    allocation_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    model_action: Mapped[str] = mapped_column(String(12), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pnl_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    user: Mapped[User] = relationship(back_populates="portfolio_positions")
    security: Mapped[Security] = relationship(back_populates="portfolio_positions")


class ConnectorState(Base):
    __tablename__ = "connector_states"
    __table_args__ = (UniqueConstraint("connector_name", name="uq_connector_states_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    connector_name: Mapped[str] = mapped_column(String(40), nullable=False)
    last_cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="idle", nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_events_created_at", "created_at"),
        Index("ix_activity_events_action", "action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_username: Mapped[str] = mapped_column(String(50), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_timestamp)

    actor: Mapped[User | None] = relationship(back_populates="activity_events")
