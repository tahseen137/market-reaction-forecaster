from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


UserRole = Literal["admin", "trial_user", "subscriber"]
SubscriptionStatus = Literal["free", "trialing", "active", "past_due", "canceled"]
RecommendationAction = Literal["buy", "hold", "sell"]
GoalPrimary = Literal["aggressive_growth", "balanced_growth", "capital_preservation", "income"]
RiskTolerance = Literal["conservative", "balanced", "aggressive"]
DrawdownBand = Literal["under_10", "under_15", "under_20", "under_30"]
HoldingPeriod = Literal["short_term", "swing", "medium_term", "long_term"]
IncomeStabilityBand = Literal["variable", "mostly_stable", "stable"]
ConcentrationTolerance = Literal["low", "medium", "high"]
ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
AgeBand = Literal["18_24", "25_34", "35_44", "45_54", "55_64", "65_plus"]
InvestableAmountBand = Literal["under_10k", "10k_50k", "50k_250k", "250k_1m", "1m_plus"]
BillingCycle = Literal["monthly", "annual"]
EventType = Literal[
    "earnings",
    "guidance",
    "product_launch",
    "regulatory",
    "macro",
    "mna",
    "analyst_rating",
    "supply_chain",
    "customer_win",
    "customer_loss",
]


class SessionLoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    next_path: str = Field(default="/")


class SessionSignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(default="", max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class TokenRequest(BaseModel):
    token: str = Field(..., min_length=12, max_length=120)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=12, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class BillingRequest(BaseModel):
    billing_cycle: BillingCycle


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    email_verified: bool
    disclosures_acknowledged_at: datetime | None
    created_at: datetime


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plan_key: str
    status: SubscriptionStatus
    trial_started_at: datetime | None
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    stripe_customer_id: str | None


class PermissionSummary(BaseModel):
    can_manage_users: bool
    has_paid_access: bool
    billing_enabled: bool


class SessionStatusResponse(BaseModel):
    auth_required: bool
    authenticated: bool
    next_path: str
    csrf_token: str | None
    current_user: CurrentUserResponse | None
    subscription: SubscriptionRead | None
    permissions: PermissionSummary


class UserProfileWrite(BaseModel):
    age_band: AgeBand
    investable_amount_band: InvestableAmountBand
    goal_primary: GoalPrimary
    risk_tolerance: RiskTolerance
    max_drawdown_band: DrawdownBand
    holding_period_preference: HoldingPeriod
    income_stability_band: IncomeStabilityBand
    sector_concentration_tolerance: ConcentrationTolerance
    experience_level: ExperienceLevel


class UserProfileRead(UserProfileWrite):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class SecurityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    company_name: str
    sector: str
    exchange: str
    is_active: bool
    last_price: float
    day_change_pct: float
    last_price_at: datetime | None


class WatchlistCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    symbols: list[str] = Field(default_factory=list)


class WatchlistRead(BaseModel):
    id: str
    name: str
    symbols: list[str]
    created_at: datetime
    updated_at: datetime


class EventCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=12)
    event_type: EventType
    headline: str = Field(..., min_length=10, max_length=280)
    summary: str = Field(default="", max_length=4000)
    thesis: str = Field(default="", max_length=4000)
    directional_bias: float = Field(default=0.0, ge=-0.5, le=0.5)
    source_label: str = Field(default="Manual Analyst Entry", max_length=80)
    source_url: str = Field(default="", max_length=500)


class SourceSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_name: str
    source_url: str
    headline: str
    summary_text: str
    published_at: datetime | None


class EventRead(BaseModel):
    id: str
    symbol: str
    event_type: str
    headline: str
    summary: str
    thesis: str
    source_label: str
    occurred_at: datetime
    directional_bias: float
    is_material: bool
    tags: list[str]
    source_snapshot: SourceSnapshotRead | None
    created_at: datetime
    updated_at: datetime


class HorizonRangeRead(BaseModel):
    horizon_days: int
    expected_return_low: float
    expected_return_mid: float
    expected_return_high: float


class PersonaSignalRead(BaseModel):
    name: str
    archetype: str
    sentiment_score: float
    position_bias: str
    confidence: float
    rationale: str


class MiroFishAnalysisRead(BaseModel):
    aggregate_sentiment: float
    aggregate_positioning: float
    consensus_strength: float
    dispersion: float
    regime: str
    explanation: str
    personas: list[PersonaSignalRead]


class ChaosAnalysisRead(BaseModel):
    chaos_score: float
    predictability_horizon_days: int
    signal_instability: float
    confidence_multiplier: float
    confidence_band: str
    explanation: str


class RecommendationDetailRead(BaseModel):
    symbol: str
    company_name: str
    action: RecommendationAction
    conviction_score: int
    confidence_score: float
    profile_fit_score: float | None
    allocation_min_pct: float | None
    allocation_max_pct: float | None
    urgency_label: str | None
    thesis_summary: str
    evidence_summary: str
    invalidation_conditions: str
    benchmark_symbol: str
    source_status: str
    analog_sample_size: int
    generated_at: datetime
    price_snapshot_at: datetime | None = None
    news_snapshot_at: datetime | None = None
    latest_event_id: str | None
    factor_scores: dict[str, float]
    horizon_ranges: list[HorizonRangeRead]
    mirofish_analysis: MiroFishAnalysisRead | None = None
    chaos_analysis: ChaosAnalysisRead | None = None
    weight_profile_name: str | None = None
    rationale: str | None = None


class RecommendationFeedEntry(RecommendationDetailRead):
    latest_headline: str | None = None
    delayed_sample: bool = False


class ModelPortfolioPositionRead(BaseModel):
    id: str
    symbol: str
    company_name: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    entry_price: float
    current_price: float
    allocation_pct: float
    model_action: str
    horizon_days: int
    pnl_pct: float
    rationale: str


class ModelPortfolioRead(BaseModel):
    positions: list[ModelPortfolioPositionRead]
    total_allocated_pct: float
    open_positions: int
    cash_pct: float
    generated_at: datetime


class BacktestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope_label: str
    benchmark_symbol: str
    universe_version: str
    generated_at: datetime
    sample_size: int
    hit_rate: float
    win_rate: float
    average_return: float
    benchmark_return: float
    max_drawdown: float
    calibration_error: float
    metadata_json: dict[str, object]


class DashboardRead(BaseModel):
    recommendation_count: int
    buy_count: int
    hold_count: int
    sell_count: int
    watchlist_count: int
    event_count: int
    open_positions: int
    benchmark_symbol: str
    top_recommendations: list[RecommendationFeedEntry]


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: str = Field(default="", max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = "trial_user"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    email_verified: bool
    disclosures_acknowledged_at: datetime | None
    created_at: datetime


class ActivityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_username: str
    action: str
    entity_type: str
    entity_id: str | None
    description: str
    details: dict[str, object]
    created_at: datetime


class ConnectorStatusRead(BaseModel):
    connector_name: str
    status: str
    last_polled_at: datetime | None
    metadata_json: dict[str, object]


class SystemStatusRead(BaseModel):
    billing_enabled: bool
    password_reset_email_enabled: bool
    scheduler_enabled: bool
    latest_refresh_at: datetime | None
    connectors: list[ConnectorStatusRead]
