from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, Iterable
import csv

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.activity_service import summarize_analytics_events
from app.autoresearch import load_autoresearch_artifact, load_weight_overrides, run_autoresearch_loop
from app.config import Settings
from app.data_sources import FinnhubClient, NormalizedEventCandidate, RssFeedClient, SecEdgarClient, TwelveDataClient, hash_content
from app.models import (
    BacktestRun,
    ConnectorState,
    Event,
    PortfolioPosition,
    RecommendationOutcome,
    RecommendationSnapshot,
    Security,
    SourceSnapshot,
    SubscriptionState,
    User,
    UserRecommendation,
    ValidationReport,
    Watchlist,
    WatchlistSecurity,
)
from app.scoring import build_backtest_metrics, build_base_recommendation, personalize_recommendation
from app.universe import BENCHMARK_SYMBOL, SAMPLE_PRICE_MAP, UNIVERSE_SECURITIES, UNIVERSE_VERSION
from app.user_service import get_subscription_state, has_paid_access, sync_role_with_subscription


IR_FEED_URLS: dict[str, str] = {
    "AAPL": "https://www.apple.com/newsroom/rss-feed.rss",
    "NVDA": "https://nvidianews.nvidia.com/releases.xml",
    "AMD": "https://ir.amd.com/rss/news-releases.xml",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _event_query() -> Select[tuple[Event]]:
    return (
        select(Event)
        .options(selectinload(Event.security), selectinload(Event.source_snapshot))
        .order_by(Event.occurred_at.desc(), Event.created_at.desc())
    )


def _recommendation_query() -> Select[tuple[RecommendationSnapshot]]:
    return (
        select(RecommendationSnapshot)
        .options(selectinload(RecommendationSnapshot.security), selectinload(RecommendationSnapshot.latest_event))
        .order_by(RecommendationSnapshot.generated_at.desc())
    )


def _connector_query() -> Select[tuple[ConnectorState]]:
    return select(ConnectorState).order_by(ConnectorState.connector_name.asc())


def _get_or_create_connector_state(session: Session, connector_name: str) -> ConnectorState:
    existing = session.scalars(select(ConnectorState).where(ConnectorState.connector_name == connector_name)).first()
    if existing is not None:
        return existing
    connector_state = ConnectorState(connector_name=connector_name, status="idle", metadata_json={})
    session.add(connector_state)
    session.commit()
    session.refresh(connector_state)
    return connector_state


def update_connector_state(
    session: Session,
    connector_name: str,
    *,
    status: str,
    metadata: dict[str, object] | None = None,
    last_polled_at: datetime | None = None,
    last_cursor: str | None = None,
) -> ConnectorState:
    connector_state = _get_or_create_connector_state(session, connector_name)
    connector_state.status = status
    connector_state.last_polled_at = last_polled_at or _now()
    if metadata is not None:
        connector_state.metadata_json = metadata
    if last_cursor is not None:
        connector_state.last_cursor = last_cursor
    session.add(connector_state)
    session.commit()
    session.refresh(connector_state)
    return connector_state


def list_connector_states(session: Session) -> list[ConnectorState]:
    return list(session.scalars(_connector_query()))


def refresh_runtime_connector_states(session: Session, settings: Settings) -> None:
    update_connector_state(
        session,
        "billing",
        status="configured" if settings.billing_enabled else "unconfigured",
        metadata={"provider": "stripe", "enabled": settings.billing_enabled},
    )
    update_connector_state(
        session,
        "password_reset_email",
        status="configured" if settings.password_reset_email_enabled else "unconfigured",
        metadata={"provider": "postmark", "enabled": settings.password_reset_email_enabled},
    )
    update_connector_state(
        session,
        "quote_feed",
        status="live" if settings.twelve_data_api_key else "fallback",
        metadata={"provider": "twelve_data", "enabled": bool(settings.twelve_data_api_key)},
    )
    update_connector_state(
        session,
        "news_feed",
        status="live" if settings.finnhub_api_key else "limited",
        metadata={"provider": "finnhub", "enabled": bool(settings.finnhub_api_key)},
    )
    update_connector_state(
        session,
        "sec_edgar",
        status="live",
        metadata={"provider": "sec_edgar", "enabled": True},
    )
    update_connector_state(
        session,
        "investor_relations_rss",
        status="live",
        metadata={"provider": "rss", "enabled": True},
    )
    update_connector_state(
        session,
        "scheduler",
        status="enabled" if settings.worker_scheduler_enabled else "disabled",
        metadata={
            "timezone": settings.market_refresh_timezone,
            "hour_local": settings.market_refresh_hour_local,
            "minute_local": settings.market_refresh_minute_local,
        },
    )


def build_system_status(session: Session, settings: Settings) -> dict[str, object]:
    refresh_runtime_connector_states(session, settings)
    connectors = list_connector_states(session)
    latest_refresh = next((item.last_polled_at for item in connectors if item.connector_name == "market_refresh"), None)
    return {
        "billing_enabled": settings.billing_enabled,
        "password_reset_email_enabled": settings.password_reset_email_enabled,
        "scheduler_enabled": settings.worker_scheduler_enabled,
        "latest_refresh_at": latest_refresh,
        "connectors": [
            {
                "connector_name": item.connector_name,
                "status": item.status,
                "last_polled_at": item.last_polled_at,
                "metadata_json": item.metadata_json,
            }
            for item in connectors
        ],
    }


VALIDATION_HORIZONS = (1, 5, 20)


def _add_trading_days(started_at: datetime, trading_days: int) -> datetime:
    cursor = _coerce_utc(started_at) or _now()
    remaining = trading_days
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


def _safe_return_pct(exit_price: float | None, entry_price: float | None) -> float:
    if not exit_price or not entry_price:
        return 0.0
    return round(((exit_price - entry_price) / entry_price) * 100, 4)


def _strategy_return_pct(action: str, observed_return_pct: float) -> float:
    if action == "buy":
        return round(observed_return_pct, 4)
    if action == "sell":
        return round(-observed_return_pct, 4)
    return 0.0


def _baseline_action_from_bias(directional_bias: float) -> str:
    if directional_bias >= 0.05:
        return "buy"
    if directional_bias <= -0.05:
        return "sell"
    return "hold"


def _directional_correct(action: str, observed_return_pct: float) -> bool:
    if action == "buy":
        return observed_return_pct > 0
    if action == "sell":
        return observed_return_pct < 0
    return abs(observed_return_pct) <= 1.5


def _report_date(value: datetime | None = None) -> str:
    return (value or _now()).date().isoformat()


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _benchmark_quote_price(settings: Settings, cache: dict[str, float] | None = None) -> float:
    if cache is not None and BENCHMARK_SYMBOL in cache:
        return cache[BENCHMARK_SYMBOL]
    price = TwelveDataClient(settings).get_quote(BENCHMARK_SYMBOL).price
    if cache is not None:
        cache[BENCHMARK_SYMBOL] = price
    return price


def _latest_snapshots(session: Session) -> list[RecommendationSnapshot]:
    snapshots = list(
        session.scalars(
            _recommendation_query().order_by(
                RecommendationSnapshot.security_id.asc(),
                RecommendationSnapshot.generated_at.desc(),
            )
        )
    )
    latest_by_security: dict[str, RecommendationSnapshot] = {}
    for snapshot in snapshots:
        latest_by_security.setdefault(snapshot.security_id, snapshot)
    return list(latest_by_security.values())


def _validation_outcome_query() -> Select[tuple[RecommendationOutcome]]:
    return (
        select(RecommendationOutcome)
        .options(
            selectinload(RecommendationOutcome.security),
            selectinload(RecommendationOutcome.recommendation_snapshot).selectinload(RecommendationSnapshot.latest_event),
            selectinload(RecommendationOutcome.recommendation_snapshot).selectinload(RecommendationSnapshot.security),
        )
        .order_by(RecommendationOutcome.created_at.desc())
    )


def _validation_report_query() -> Select[tuple[ValidationReport]]:
    return select(ValidationReport).order_by(ValidationReport.generated_at.desc())


def ensure_recommendation_outcomes(session: Session, snapshot: RecommendationSnapshot) -> list[RecommendationOutcome]:
    existing = list(
        session.scalars(
            _validation_outcome_query().where(RecommendationOutcome.recommendation_snapshot_id == snapshot.id)
        )
    )
    if existing:
        return existing

    outcomes: list[RecommendationOutcome] = []
    for horizon_days in VALIDATION_HORIZONS:
        outcome = RecommendationOutcome(
            recommendation_snapshot_id=snapshot.id,
            security_id=snapshot.security_id,
            action=snapshot.action,
            confidence_score=snapshot.confidence_score,
            horizon_days=horizon_days,
            benchmark_symbol=snapshot.benchmark_symbol,
            status="open",
            target_at=_add_trading_days(snapshot.generated_at, horizon_days),
            reference_price=snapshot.reference_price,
            benchmark_reference_price=snapshot.benchmark_reference_price,
            metadata_json={"model_version": snapshot.model_version},
        )
        session.add(outcome)
        outcomes.append(outcome)
    session.commit()
    return list(
        session.scalars(
            _validation_outcome_query().where(RecommendationOutcome.recommendation_snapshot_id == snapshot.id)
        )
    )


def ensure_validation_outcomes_for_all_snapshots(session: Session) -> None:
    snapshots = list(
        session.scalars(
            _recommendation_query()
            .options(selectinload(RecommendationSnapshot.latest_event), selectinload(RecommendationSnapshot.security))
        )
    )
    for snapshot in snapshots:
        ensure_recommendation_outcomes(session, snapshot)


def resolve_due_recommendation_outcomes(session: Session, settings: Settings) -> list[RecommendationOutcome]:
    due_outcomes = list(
        session.scalars(
            _validation_outcome_query().where(
                RecommendationOutcome.status == "open",
                RecommendationOutcome.target_at <= _now(),
            )
        )
    )
    if not due_outcomes:
        return []

    quote_client = TwelveDataClient(settings)
    benchmark_quotes: dict[str, float] = {}
    security_quotes: dict[str, float] = {}
    resolved_at = _now()

    for outcome in due_outcomes:
        symbol = outcome.security.symbol
        benchmark_symbol = outcome.benchmark_symbol
        security_price = security_quotes.get(symbol)
        if security_price is None:
            security_quote = quote_client.get_quote(symbol)
            security_price = security_quote.price
            security_quotes[symbol] = security_price
            outcome.security.last_price = security_quote.price
            outcome.security.day_change_pct = security_quote.day_change_pct
            outcome.security.last_price_at = security_quote.as_of
            session.add(outcome.security)
        benchmark_price = benchmark_quotes.get(benchmark_symbol)
        if benchmark_price is None:
            benchmark_price = quote_client.get_quote(benchmark_symbol).price
            benchmark_quotes[benchmark_symbol] = benchmark_price

        observed_return_pct = _safe_return_pct(security_price, outcome.reference_price)
        benchmark_return_pct = _safe_return_pct(benchmark_price, outcome.benchmark_reference_price)
        strategy_return_pct = _strategy_return_pct(outcome.action, observed_return_pct)
        bias = outcome.recommendation_snapshot.latest_event.directional_bias if outcome.recommendation_snapshot.latest_event else 0.0
        baseline_action = _baseline_action_from_bias(bias)
        baseline_return_pct = _strategy_return_pct(baseline_action, observed_return_pct)

        outcome.status = "resolved"
        outcome.resolved_at = resolved_at
        outcome.observed_price = security_price
        outcome.benchmark_observed_price = benchmark_price
        outcome.observed_return_pct = observed_return_pct
        outcome.strategy_return_pct = strategy_return_pct
        outcome.benchmark_return_pct = benchmark_return_pct
        outcome.excess_return_pct = round(strategy_return_pct - benchmark_return_pct, 4)
        outcome.baseline_action = baseline_action
        outcome.baseline_return_pct = baseline_return_pct
        outcome.directional_correct = _directional_correct(outcome.action, observed_return_pct)
        outcome.metadata_json = {
            **outcome.metadata_json,
            "resolved_symbol": symbol,
            "resolved_benchmark": benchmark_symbol,
        }
        session.add(outcome)

    session.commit()
    return due_outcomes


def list_validation_reports(session: Session, *, limit: int = 30) -> list[ValidationReport]:
    return list(session.scalars(_validation_report_query().limit(limit)))


def get_latest_validation_report(session: Session) -> ValidationReport | None:
    return session.scalars(_validation_report_query().limit(1)).first()


def list_reference_universe(session: Session) -> list[Security]:
    statement = select(Security).where(Security.is_active.is_(True)).order_by(Security.symbol.asc())
    return list(session.scalars(statement))


def get_security_by_symbol(session: Session, symbol: str) -> Security | None:
    statement = select(Security).where(Security.symbol == symbol.strip().upper())
    return session.scalars(statement).first()


def seed_universe(session: Session) -> None:
    existing_symbols = {security.symbol for security in list_reference_universe(session)}
    for payload in UNIVERSE_SECURITIES:
        symbol = payload["symbol"]
        if symbol in existing_symbols:
            continue
        session.add(
            Security(
                symbol=symbol,
                company_name=payload["company_name"],
                sector=payload["sector"],
                exchange=payload["exchange"],
                cik=payload["cik"],
                is_active=True,
                last_price=SAMPLE_PRICE_MAP.get(symbol, 100.0),
                day_change_pct=0.5,
                last_price_at=_now(),
            )
        )
    session.commit()


def _create_source_snapshot(session: Session, candidate: NormalizedEventCandidate) -> SourceSnapshot:
    existing = session.scalars(select(SourceSnapshot).where(SourceSnapshot.content_hash == candidate.content_hash)).first()
    if existing:
        return existing
    snapshot = SourceSnapshot(
        source_type=candidate.source_type,
        source_name=candidate.source_label,
        source_url=candidate.source_url,
        headline=candidate.headline,
        summary_text=candidate.summary,
        raw_payload={
            "symbol": candidate.symbol,
            "event_type": candidate.event_type,
            "thesis": candidate.thesis,
            "tags": candidate.tags,
        },
        content_hash=candidate.content_hash,
        published_at=candidate.occurred_at,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def _analog_count(session: Session, security_id: str, event_type: str) -> int:
    statement = select(func.count()).select_from(Event).where(Event.security_id == security_id, Event.event_type == event_type)
    return int(session.scalar(statement) or 0)


def _latest_event_for_security(session: Session, security_id: str) -> Event | None:
    statement = _event_query().where(Event.security_id == security_id).limit(1)
    return session.scalars(statement).first()


def create_event(session: Session, *, symbol: str, candidate: NormalizedEventCandidate) -> Event:
    security = get_security_by_symbol(session, symbol)
    if security is None:
        raise ValueError("Security is not in the launch universe")
    dedupe_key = hash_content(candidate.symbol, candidate.event_type, candidate.headline, candidate.source_url, candidate.occurred_at.isoformat())
    existing = session.scalars(select(Event).where(Event.dedupe_key == dedupe_key)).first()
    if existing:
        return existing
    snapshot = _create_source_snapshot(session, candidate)
    event = Event(
        security_id=security.id,
        source_snapshot_id=snapshot.id,
        event_type=candidate.event_type,
        headline=candidate.headline,
        summary=candidate.summary,
        thesis=candidate.thesis,
        source_label=candidate.source_label,
        occurred_at=candidate.occurred_at,
        directional_bias=candidate.directional_bias,
        is_material=True,
        dedupe_key=dedupe_key,
        tags=candidate.tags,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def list_events(session: Session, *, limit: int = 50, symbol: str | None = None) -> list[Event]:
    statement = _event_query()
    if symbol:
        security = get_security_by_symbol(session, symbol)
        if security is None:
            return []
        statement = statement.where(Event.security_id == security.id)
    return list(session.scalars(statement.limit(limit)))


def get_event(session: Session, event_id: str) -> Event | None:
    return session.scalars(_event_query().where(Event.id == event_id)).first()


def refresh_security_quote(session: Session, settings: Settings, security: Security) -> Security:
    quote = TwelveDataClient(settings).get_quote(security.symbol)
    security.last_price = quote.price
    security.day_change_pct = quote.day_change_pct
    security.last_price_at = quote.as_of
    session.add(security)
    session.commit()
    session.refresh(security)
    return security


def rebuild_security_recommendation(
    session: Session,
    settings: Settings,
    security: Security,
    *,
    benchmark_reference_price: float | None = None,
    force: bool = False,
) -> RecommendationSnapshot:
    # Check if we already have a snapshot generated today (since market open)
    # Market opens at 9:30 AM ET, so we use 9:00 AM ET as the cutoff
    # Skip this check if force=True (for backfilling missing artifacts, etc)
    if not force:
        today_cutoff = _now().replace(hour=13, minute=0, second=0, microsecond=0)  # 9:00 AM ET = 13:00 UTC
        if today_cutoff > _now():
            # If it's before 9 AM ET today, use yesterday's 9 AM ET as cutoff
            today_cutoff = today_cutoff - timedelta(days=1)
        
        existing_snapshot = session.scalars(
            select(RecommendationSnapshot)
            .where(
                RecommendationSnapshot.security_id == security.id,
                RecommendationSnapshot.generated_at >= today_cutoff,
            )
            .order_by(RecommendationSnapshot.generated_at.desc())
            .limit(1)
        ).first()
        
        if existing_snapshot is not None:
            # Return existing snapshot if one was generated today
            return existing_snapshot
    
    latest_event = _latest_event_for_security(session, security.id)
    if latest_event is None:
        latest_event = create_event(
            session,
            symbol=security.symbol,
            candidate=NormalizedEventCandidate(
                symbol=security.symbol,
                event_type="macro",
                headline=f"{security.symbol} baseline market pulse",
                summary=f"Baseline seeded event for {security.symbol} to support launch coverage.",
                thesis=f"Baseline seeded event for {security.symbol}.",
                source_label="Manual Analyst Entry",
                source_type="manual",
                source_url="",
                occurred_at=_now() - timedelta(days=2),
                directional_bias=0.0,
                tags=["seed"],
                content_hash=hash_content(security.symbol, "baseline"),
            ),
        )
    analog_count = _analog_count(session, security.id, latest_event.event_type)
    weight_overrides, weight_profile_name = load_weight_overrides(settings)
    base = build_base_recommendation(
        symbol=security.symbol,
        company_name=security.company_name,
        event_type=latest_event.event_type,
        headline=latest_event.headline,
        summary=latest_event.summary,
        source_label=latest_event.source_label,
        directional_bias=latest_event.directional_bias,
        day_change_pct=security.day_change_pct,
        analog_count=analog_count,
        source_status="real-time" if settings.twelve_data_api_key else "delayed",
        benchmark_symbol=BENCHMARK_SYMBOL,
        weight_overrides=weight_overrides,
        weight_profile_name=weight_profile_name,
    )
    snapshot = RecommendationSnapshot(
        security_id=security.id,
        latest_event_id=latest_event.id,
        model_version=settings.recommendation_model_version,
        action=base.action,
        conviction_score=base.conviction_score,
        confidence_score=base.confidence_score,
        analog_sample_size=base.analog_sample_size,
        benchmark_symbol=base.benchmark_symbol,
        reference_price=security.last_price,
        benchmark_reference_price=benchmark_reference_price or _benchmark_quote_price(settings),
        source_status=base.source_status,
        thesis_summary=base.thesis_summary,
        evidence_summary=base.evidence_summary,
        invalidation_conditions=base.invalidation_conditions,
        factor_scores=base.factor_scores,
        horizon_ranges=base.horizon_ranges,
        analysis_artifacts=base.analysis_artifacts,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    ensure_recommendation_outcomes(session, snapshot)
    return snapshot


def default_profile_payload() -> dict[str, str]:
    return {
        "age_band": "25_34",
        "investable_amount_band": "10k_50k",
        "goal_primary": "balanced_growth",
        "risk_tolerance": "balanced",
        "max_drawdown_band": "under_20",
        "holding_period_preference": "medium_term",
        "income_stability_band": "mostly_stable",
        "sector_concentration_tolerance": "medium",
        "experience_level": "intermediate",
    }


def rebuild_user_recommendations_for_user(session: Session, user: User) -> list[UserRecommendation]:
    profile = user.profile
    if profile is None:
        return []
    snapshots = _latest_snapshots(session)
    if not snapshots:
        return []
    session.query(UserRecommendation).filter(UserRecommendation.user_id == user.id).delete()  # type: ignore[attr-defined]
    recommendations: list[UserRecommendation] = []
    for snapshot in snapshots:
        snapshot_weights = snapshot.analysis_artifacts.get("weights", {}) if snapshot.analysis_artifacts else {}
        personalized = personalize_recommendation(
            build_base_recommendation(
                symbol=snapshot.security.symbol,
                company_name=snapshot.security.company_name,
                event_type=snapshot.latest_event.event_type if snapshot.latest_event else "macro",
                headline=snapshot.latest_event.headline if snapshot.latest_event else snapshot.security.company_name,
                summary=snapshot.latest_event.summary if snapshot.latest_event else "",
                source_label=snapshot.latest_event.source_label if snapshot.latest_event else "Manual Analyst Entry",
                directional_bias=snapshot.latest_event.directional_bias if snapshot.latest_event else 0.0,
                day_change_pct=snapshot.security.day_change_pct,
                analog_count=snapshot.analog_sample_size,
                source_status=snapshot.source_status,
                benchmark_symbol=snapshot.benchmark_symbol,
                weight_overrides=snapshot_weights.get("overrides") if isinstance(snapshot_weights, dict) else None,
                weight_profile_name=snapshot_weights.get("profile_name", "baseline") if isinstance(snapshot_weights, dict) else "baseline",
            ),
            goal_primary=profile.goal_primary,
            risk_tolerance=profile.risk_tolerance,
            max_drawdown_band=profile.max_drawdown_band,
            holding_period_preference=profile.holding_period_preference,
            sector_concentration_tolerance=profile.sector_concentration_tolerance,
            experience_level=profile.experience_level,
        )
        recommendation = UserRecommendation(
            user_id=user.id,
            recommendation_snapshot_id=snapshot.id,
            action=personalized.action,
            conviction_score=personalized.conviction_score,
            profile_fit_score=personalized.profile_fit_score,
            allocation_min_pct=personalized.allocation_min_pct,
            allocation_max_pct=personalized.allocation_max_pct,
            urgency_label=personalized.urgency_label,
            rationale=personalized.rationale,
            profile_inputs_snapshot=default_profile_payload() | {
                "goal_primary": profile.goal_primary,
                "risk_tolerance": profile.risk_tolerance,
                "max_drawdown_band": profile.max_drawdown_band,
                "holding_period_preference": profile.holding_period_preference,
                "sector_concentration_tolerance": profile.sector_concentration_tolerance,
                "experience_level": profile.experience_level,
            },
        )
        session.add(recommendation)
        recommendations.append(recommendation)
    session.commit()
    return list(
        session.scalars(
            select(UserRecommendation)
            .where(UserRecommendation.user_id == user.id)
            .options(selectinload(UserRecommendation.recommendation_snapshot).selectinload(RecommendationSnapshot.security))
            .order_by(UserRecommendation.conviction_score.desc(), UserRecommendation.created_at.desc())
        )
    )


def rebuild_all_user_recommendations(session: Session) -> None:
    users = list(session.scalars(select(User).options(selectinload(User.profile), selectinload(User.subscription_state))))
    for user in users:
        if user.profile is None:
            continue
        rebuild_user_recommendations_for_user(session, user)


def _latest_snapshot_for_symbol(session: Session, symbol: str) -> RecommendationSnapshot | None:
    security = get_security_by_symbol(session, symbol)
    if security is None:
        return None
    statement = _recommendation_query().where(RecommendationSnapshot.security_id == security.id).limit(1)
    return session.scalars(statement).first()


def _recommendation_to_feed_entry(snapshot: RecommendationSnapshot, user_recommendation: UserRecommendation | None, *, delayed_sample: bool) -> dict[str, object]:
    latest_event = snapshot.latest_event
    analysis_artifacts = snapshot.analysis_artifacts or {}
    weights = analysis_artifacts.get("weights", {}) if isinstance(analysis_artifacts, dict) else {}
    return {
        "symbol": snapshot.security.symbol,
        "company_name": snapshot.security.company_name,
        "action": (user_recommendation.action if user_recommendation else snapshot.action),
        "conviction_score": user_recommendation.conviction_score if user_recommendation else snapshot.conviction_score,
        "confidence_score": snapshot.confidence_score,
        "profile_fit_score": user_recommendation.profile_fit_score if user_recommendation else None,
        "allocation_min_pct": user_recommendation.allocation_min_pct if user_recommendation else None,
        "allocation_max_pct": user_recommendation.allocation_max_pct if user_recommendation else None,
        "urgency_label": user_recommendation.urgency_label if user_recommendation else None,
        "thesis_summary": snapshot.thesis_summary,
        "evidence_summary": snapshot.evidence_summary,
        "invalidation_conditions": snapshot.invalidation_conditions,
        "benchmark_symbol": snapshot.benchmark_symbol,
        "source_status": snapshot.source_status,
        "analog_sample_size": snapshot.analog_sample_size,
        "generated_at": snapshot.generated_at,
        "price_snapshot_at": snapshot.security.last_price_at,
        "news_snapshot_at": latest_event.created_at if latest_event else None,
        "latest_event_id": snapshot.latest_event_id,
        "factor_scores": snapshot.factor_scores,
        "horizon_ranges": snapshot.horizon_ranges,
        "mirofish_analysis": analysis_artifacts.get("mirofish") if isinstance(analysis_artifacts, dict) else None,
        "chaos_analysis": analysis_artifacts.get("chaos") if isinstance(analysis_artifacts, dict) else None,
        "weight_profile_name": weights.get("profile_name") if isinstance(weights, dict) else None,
        "rationale": user_recommendation.rationale if user_recommendation else None,
        "latest_headline": latest_event.headline if latest_event else None,
        "delayed_sample": delayed_sample,
    }


def get_recommendation_feed(session: Session, *, user: User | None = None, sample_limit: int = 6) -> list[dict[str, object]]:
    snapshots = _latest_snapshots(session)
    if not snapshots:
        return []
    if user is None or not has_paid_access(user) or user.disclosures_acknowledged_at is None:
        delayed_cutoff = _now() - timedelta(hours=24)
        delayed = [snapshot for snapshot in snapshots if (_coerce_utc(snapshot.generated_at) or _now()) <= delayed_cutoff]
        if not delayed:
            delayed = snapshots[:sample_limit]
        delayed.sort(key=lambda snapshot: snapshot.conviction_score, reverse=True)
        return [_recommendation_to_feed_entry(snapshot, None, delayed_sample=True) for snapshot in delayed[:sample_limit]]

    user_recs = {
        recommendation.recommendation_snapshot_id: recommendation
        for recommendation in session.scalars(
            select(UserRecommendation)
            .where(UserRecommendation.user_id == user.id)
            .options(selectinload(UserRecommendation.recommendation_snapshot))
        )
    }
    feed = [_recommendation_to_feed_entry(snapshot, user_recs.get(snapshot.id), delayed_sample=False) for snapshot in snapshots]
    feed.sort(key=lambda item: (item["conviction_score"], item["confidence_score"]), reverse=True)
    return feed


def get_recommendation_detail(session: Session, symbol: str, *, user: User | None = None) -> dict[str, object] | None:
    snapshot = _latest_snapshot_for_symbol(session, symbol)
    if snapshot is None:
        return None
    user_rec = None
    if user is not None:
        statement = select(UserRecommendation).where(
            UserRecommendation.user_id == user.id,
            UserRecommendation.recommendation_snapshot_id == snapshot.id,
        )
        user_rec = session.scalars(statement).first()
    return _recommendation_to_feed_entry(snapshot, user_rec, delayed_sample=(user is None or not has_paid_access(user)))


def create_watchlist(session: Session, user: User, *, name: str, symbols: Iterable[str]) -> Watchlist:
    watchlist = Watchlist(user_id=user.id, name=name.strip())
    session.add(watchlist)
    session.commit()
    session.refresh(watchlist)
    for symbol in symbols:
        security = get_security_by_symbol(session, symbol)
        if security is None:
            continue
        session.add(WatchlistSecurity(watchlist_id=watchlist.id, security_id=security.id))
    session.commit()
    session.refresh(watchlist)
    return watchlist


def list_watchlists(session: Session, user: User) -> list[Watchlist]:
    statement = (
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .options(selectinload(Watchlist.securities).selectinload(WatchlistSecurity.security))
        .order_by(Watchlist.updated_at.desc())
    )
    return list(session.scalars(statement))


def rebuild_model_portfolio_for_user(session: Session, user: User) -> list[PortfolioPosition]:
    recommendations = list(
        session.scalars(
            select(UserRecommendation)
            .where(UserRecommendation.user_id == user.id)
            .options(selectinload(UserRecommendation.recommendation_snapshot).selectinload(RecommendationSnapshot.security))
            .order_by(UserRecommendation.conviction_score.desc(), UserRecommendation.profile_fit_score.desc())
        )
    )
    session.query(PortfolioPosition).filter(PortfolioPosition.user_id == user.id, PortfolioPosition.status == "open").update(  # type: ignore[attr-defined]
        {"status": "closed", "closed_at": _now()},
        synchronize_session=False,
    )
    open_recommendations = [rec for rec in recommendations if rec.action == "buy"][:10]
    positions: list[PortfolioPosition] = []
    total_target = sum(max(rec.allocation_min_pct, rec.allocation_max_pct) for rec in open_recommendations) or 0.0
    for recommendation in open_recommendations:
        security = recommendation.recommendation_snapshot.security
        allocation = recommendation.allocation_max_pct
        if total_target > 100:
            allocation = allocation / total_target * 100
        position = PortfolioPosition(
            user_id=user.id,
            security_id=security.id,
            status="open",
            entry_price=security.last_price,
            current_price=security.last_price,
            allocation_pct=round(allocation, 2),
            model_action=recommendation.action,
            horizon_days=int(recommendation.recommendation_snapshot.factor_scores.get("predictability_horizon_days", 20.0)),
            rationale=recommendation.rationale,
            pnl_pct=0.0,
        )
        session.add(position)
        positions.append(position)
    session.commit()
    return list(
        session.scalars(
            select(PortfolioPosition)
            .where(PortfolioPosition.user_id == user.id)
            .options(selectinload(PortfolioPosition.security))
            .order_by(PortfolioPosition.opened_at.desc())
        )
    )


def build_model_portfolio(session: Session, user: User) -> dict[str, object]:
    positions = list(
        session.scalars(
            select(PortfolioPosition)
            .where(PortfolioPosition.user_id == user.id)
            .options(selectinload(PortfolioPosition.security))
            .order_by(PortfolioPosition.opened_at.desc())
        )
    )
    open_positions = [position for position in positions if position.status == "open"]
    total_allocated = round(sum(position.allocation_pct for position in open_positions), 2)
    generated_at = max((position.updated_at for position in positions), default=_now())
    return {
        "positions": [
            {
                "id": position.id,
                "symbol": position.security.symbol,
                "company_name": position.security.company_name,
                "status": position.status,
                "opened_at": position.opened_at,
                "closed_at": position.closed_at,
                "entry_price": position.entry_price,
                "current_price": position.current_price,
                "allocation_pct": position.allocation_pct,
                "model_action": position.model_action,
                "horizon_days": position.horizon_days,
                "pnl_pct": position.pnl_pct,
                "rationale": position.rationale,
            }
            for position in positions
        ],
        "total_allocated_pct": total_allocated,
        "open_positions": len(open_positions),
        "cash_pct": round(max(0.0, 100 - total_allocated), 2),
        "generated_at": generated_at,
    }


def refresh_backtest(session: Session) -> BacktestRun:
    snapshots = list(session.scalars(_recommendation_query()))
    sample_size = len(snapshots)
    avg_confidence = sum(snapshot.confidence_score for snapshot in snapshots) / sample_size if sample_size else 0.56
    buy_count = sum(1 for snapshot in snapshots if snapshot.action == "buy")
    sell_count = sum(1 for snapshot in snapshots if snapshot.action == "sell")
    metrics = build_backtest_metrics(
        sample_size=max(sample_size, 24),
        buy_count=buy_count,
        sell_count=sell_count,
        avg_confidence=avg_confidence or 0.56,
    )
    run = BacktestRun(
        scope_label="Large-cap tech AI recommendation benchmark",
        benchmark_symbol=BENCHMARK_SYMBOL,
        universe_version=UNIVERSE_VERSION,
        sample_size=metrics.sample_size,
        hit_rate=metrics.hit_rate,
        win_rate=metrics.win_rate,
        average_return=metrics.average_return,
        benchmark_return=metrics.benchmark_return,
        max_drawdown=metrics.max_drawdown,
        calibration_error=metrics.calibration_error,
        metadata_json={
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_confidence": round(avg_confidence, 2),
        },
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_latest_backtest(session: Session) -> BacktestRun:
    statement = select(BacktestRun).order_by(BacktestRun.generated_at.desc()).limit(1)
    run = session.scalars(statement).first()
    return run or refresh_backtest(session)


def build_dashboard(session: Session, user: User | None = None) -> dict[str, object]:
    feed = get_recommendation_feed(session, user=user)
    return {
        "recommendation_count": len(feed),
        "buy_count": sum(1 for item in feed if item["action"] == "buy"),
        "hold_count": sum(1 for item in feed if item["action"] == "hold"),
        "sell_count": sum(1 for item in feed if item["action"] == "sell"),
        "watchlist_count": len(list_watchlists(session, user)) if user else 0,
        "event_count": int(session.scalar(select(func.count()).select_from(Event)) or 0),
        "open_positions": len([position for position in build_model_portfolio(session, user)["positions"] if position["status"] == "open"]) if user else 0,
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "top_recommendations": feed[:6],
    }


def build_shadow_portfolio_summary(session: Session, settings: Settings) -> dict[str, object]:
    latest_buy_snapshots = [
        snapshot
        for snapshot in sorted(_latest_snapshots(session), key=lambda item: (item.conviction_score, item.confidence_score), reverse=True)
        if snapshot.action == "buy"
    ][:10]
    if not latest_buy_snapshots:
        return {
            "positions": [],
            "open_positions": 0,
            "average_strategy_return_pct": 0.0,
            "average_benchmark_return_pct": 0.0,
            "average_excess_return_pct": 0.0,
        }

    strategy_returns: list[float] = []
    benchmark_returns: list[float] = []
    positions: list[dict[str, object]] = []
    benchmark_price = _benchmark_quote_price(settings)
    for snapshot in latest_buy_snapshots:
        current_return_pct = _safe_return_pct(snapshot.security.last_price, snapshot.reference_price)
        benchmark_return_pct = _safe_return_pct(benchmark_price, snapshot.benchmark_reference_price)
        excess_return_pct = round(current_return_pct - benchmark_return_pct, 4)
        strategy_returns.append(current_return_pct)
        benchmark_returns.append(benchmark_return_pct)
        positions.append(
            {
                "symbol": snapshot.security.symbol,
                "action": snapshot.action,
                "generated_at": snapshot.generated_at,
                "reference_price": snapshot.reference_price,
                "current_price": snapshot.security.last_price,
                "benchmark_symbol": snapshot.benchmark_symbol,
                "benchmark_reference_price": snapshot.benchmark_reference_price,
                "benchmark_current_price": benchmark_price,
                "strategy_return_pct": current_return_pct,
                "benchmark_return_pct": benchmark_return_pct,
                "excess_return_pct": excess_return_pct,
                "confidence_score": snapshot.confidence_score,
            }
        )

    return {
        "positions": positions,
        "open_positions": len(positions),
        "average_strategy_return_pct": _average(strategy_returns),
        "average_benchmark_return_pct": _average(benchmark_returns),
        "average_excess_return_pct": round(_average(strategy_returns) - _average(benchmark_returns), 4),
    }


def build_validation_summary(session: Session, settings: Settings, *, lookback_days: int = 14) -> dict[str, Any]:
    analytics = summarize_analytics_events(session, lookback_days=lookback_days)
    outcomes = list(session.scalars(_validation_outcome_query()))
    resolved_outcomes = [outcome for outcome in outcomes if outcome.status == "resolved" and outcome.strategy_return_pct is not None]
    open_outcomes = [outcome for outcome in outcomes if outcome.status == "open"]

    by_horizon: dict[str, dict[str, object]] = {}
    for horizon in VALIDATION_HORIZONS:
        horizon_outcomes = [item for item in resolved_outcomes if item.horizon_days == horizon]
        by_horizon[str(horizon)] = {
            "count": len(horizon_outcomes),
            "hit_rate": _average([1.0 if item.directional_correct else 0.0 for item in horizon_outcomes]) if horizon_outcomes else 0.0,
            "average_strategy_return_pct": _average([float(item.strategy_return_pct or 0.0) for item in horizon_outcomes]),
            "average_benchmark_return_pct": _average([float(item.benchmark_return_pct or 0.0) for item in horizon_outcomes]),
            "average_excess_return_pct": _average([float(item.excess_return_pct or 0.0) for item in horizon_outcomes]),
        }

    by_action: dict[str, dict[str, object]] = {}
    for action in ("buy", "hold", "sell"):
        action_outcomes = [item for item in resolved_outcomes if item.action == action]
        by_action[action] = {
            "count": len(action_outcomes),
            "average_strategy_return_pct": _average([float(item.strategy_return_pct or 0.0) for item in action_outcomes]),
            "average_baseline_return_pct": _average([float(item.baseline_return_pct or 0.0) for item in action_outcomes]),
            "average_excess_return_pct": _average([float(item.excess_return_pct or 0.0) for item in action_outcomes]),
        }

    confidence_buckets: dict[str, dict[str, object]] = {}
    bucket_rules = {
        "high": lambda value: value >= 0.67,
        "medium": lambda value: 0.5 <= value < 0.67,
        "low": lambda value: value < 0.5,
    }
    for label, predicate in bucket_rules.items():
        bucket_outcomes = [item for item in resolved_outcomes if predicate(item.confidence_score)]
        confidence_buckets[label] = {
            "count": len(bucket_outcomes),
            "average_strategy_return_pct": _average([float(item.strategy_return_pct or 0.0) for item in bucket_outcomes]),
            "hit_rate": _average([1.0 if item.directional_correct else 0.0 for item in bucket_outcomes]) if bucket_outcomes else 0.0,
        }

    forecast_metrics = {
        "resolved_outcomes": len(resolved_outcomes),
        "open_outcomes": len(open_outcomes),
        "coverage_count": int(session.scalar(select(func.count()).select_from(RecommendationSnapshot)) or 0),
        "by_horizon": by_horizon,
        "by_action": by_action,
        "confidence_buckets": confidence_buckets,
    }
    shadow_portfolio = build_shadow_portfolio_summary(session, settings)
    autoresearch_artifact = load_autoresearch_artifact(settings)

    latest_report = get_latest_validation_report(session)
    return {
        "generated_at": _now(),
        "report_date": _report_date(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "lookback_days": lookback_days,
        "funnel": analytics,
        "forecast_metrics": forecast_metrics,
        "shadow_portfolio": shadow_portfolio,
        "autoresearch": autoresearch_artifact,
        "latest_report_id": latest_report.id if latest_report else None,
        "connector_status": build_system_status(session, settings),
    }


def refresh_validation_report(session: Session, settings: Settings) -> ValidationReport:
    ensure_validation_outcomes_for_all_snapshots(session)
    resolve_due_recommendation_outcomes(session, settings)
    autoresearch_artifact = run_autoresearch_loop(session, settings)
    summary = build_validation_summary(session, settings)
    report_date = str(summary["report_date"])
    report = session.scalars(select(ValidationReport).where(ValidationReport.report_date == report_date)).first()
    if report is None:
        report = ValidationReport(report_date=report_date, benchmark_symbol=BENCHMARK_SYMBOL)
    report.generated_at = _now()
    report.funnel_json = _json_ready(dict(summary["funnel"]))
    report.forecast_metrics_json = _json_ready(dict(summary["forecast_metrics"]))
    report.shadow_portfolio_json = _json_ready(dict(summary["shadow_portfolio"]))
    report.metadata_json = _json_ready({
        "lookback_days": summary["lookback_days"],
        "connector_status": summary["connector_status"],
        "autoresearch": autoresearch_artifact,
    })
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def build_recommendation_snapshot_export(session: Session) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "snapshot_id",
            "symbol",
            "generated_at",
            "action",
            "conviction_score",
            "confidence_score",
            "reference_price",
            "benchmark_symbol",
            "benchmark_reference_price",
            "latest_event_id",
            "model_version",
        ]
    )
    snapshots = list(
        session.scalars(
            _recommendation_query().options(selectinload(RecommendationSnapshot.security))
        )
    )
    for snapshot in snapshots:
        writer.writerow(
            [
                snapshot.id,
                snapshot.security.symbol,
                snapshot.generated_at.isoformat(),
                snapshot.action,
                snapshot.conviction_score,
                snapshot.confidence_score,
                snapshot.reference_price,
                snapshot.benchmark_symbol,
                snapshot.benchmark_reference_price,
                snapshot.latest_event_id or "",
                snapshot.model_version,
            ]
        )
    return buffer.getvalue()


def build_validation_report_export(session: Session) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "report_date",
            "generated_at",
            "benchmark_symbol",
            "active_user_count",
            "signup_completed",
            "checkout_started",
            "checkout_completed",
            "resolved_outcomes",
            "open_outcomes",
            "shadow_open_positions",
            "shadow_average_excess_return_pct",
        ]
    )
    for report in list_validation_reports(session):
        writer.writerow(
            [
                report.report_date,
                report.generated_at.isoformat(),
                report.benchmark_symbol,
                report.funnel_json.get("active_user_count", 0),
                report.funnel_json.get("counts", {}).get("signup_completed", 0),
                report.funnel_json.get("counts", {}).get("checkout_started", 0),
                report.funnel_json.get("counts", {}).get("checkout_completed", 0),
                report.forecast_metrics_json.get("resolved_outcomes", 0),
                report.forecast_metrics_json.get("open_outcomes", 0),
                report.shadow_portfolio_json.get("open_positions", 0),
                report.shadow_portfolio_json.get("average_excess_return_pct", 0.0),
            ]
        )
    return buffer.getvalue()


def create_or_update_trial_state(session: Session, user: User, settings: Settings) -> SubscriptionState:
    subscription = get_subscription_state(user)
    if subscription.status == "free":
        subscription.status = "trialing"
        subscription.plan_key = "pro_trial"
        subscription.trial_started_at = _now()
        subscription.trial_ends_at = _now() + timedelta(days=settings.trial_days)
        sync_role_with_subscription(user)
        session.add_all([subscription, user])
        session.commit()
    return subscription


def ingest_candidate_events(session: Session, settings: Settings, security: Security) -> int:
    created = 0
    sources = [
        *SecEdgarClient(settings).get_recent_filings(security.symbol, security.cik),
        *FinnhubClient(settings).get_company_news(security.symbol),
    ]
    feed_url = IR_FEED_URLS.get(security.symbol)
    if feed_url:
        sources.extend(RssFeedClient().get_items(security.symbol, feed_url))
    for candidate in sources:
        before = int(session.scalar(select(func.count()).select_from(Event)) or 0)
        create_event(session, symbol=security.symbol, candidate=candidate)
        after = int(session.scalar(select(func.count()).select_from(Event)) or 0)
        if after > before:
            created += 1
    if created:
        rebuild_security_recommendation(session, settings, security)
    return created


def refresh_market_state(session: Session, settings: Settings) -> None:
    started_at = _now()
    update_connector_state(session, "market_refresh", status="running", metadata={"started_at": started_at.isoformat()}, last_polled_at=started_at)
    refresh_runtime_connector_states(session, settings)
    refreshed_symbols: list[str] = []
    created_events = 0
    benchmark_reference_price = _benchmark_quote_price(settings)
    for security in list_reference_universe(session):
        refresh_security_quote(session, settings, security)
        created_events += ingest_candidate_events(session, settings, security)
        rebuild_security_recommendation(session, settings, security, benchmark_reference_price=benchmark_reference_price)
        refreshed_symbols.append(security.symbol)
    rebuild_all_user_recommendations(session)
    backtest = refresh_backtest(session)
    validation_report = refresh_validation_report(session, settings)
    update_connector_state(
        session,
        "market_refresh",
        status="ok",
        last_polled_at=_now(),
        metadata={
            "started_at": started_at.isoformat(),
            "refreshed_symbols": refreshed_symbols,
            "created_events": created_events,
            "backtest_run_id": backtest.id,
            "validation_report_id": validation_report.id,
        },
    )


def seed_demo_content(session: Session, settings: Settings) -> None:
    refresh_runtime_connector_states(session, settings)
    if session.scalars(select(Event).limit(1)).first():
        for security in list_reference_universe(session):
            latest_snapshot = _latest_snapshot_for_symbol(session, security.symbol)
            analysis_artifacts = latest_snapshot.analysis_artifacts if latest_snapshot is not None else None
            if latest_snapshot is None or not isinstance(analysis_artifacts, dict) or not analysis_artifacts.get("mirofish") or not analysis_artifacts.get("chaos"):
                rebuild_security_recommendation(session, settings, security, force=True)
        return
    now = _now()
    seeded_candidates = [
        NormalizedEventCandidate(
            symbol="NVDA",
            event_type="earnings",
            headline="NVIDIA beats expectations and raises AI data center guidance",
            summary="The company lifted near-term guidance on accelerating hyperscaler demand.",
            thesis="Raised guidance plus stronger AI demand supports continued positive revision momentum.",
            source_label="Manual Analyst Entry",
            source_type="manual",
            source_url="",
            occurred_at=now - timedelta(days=3),
            directional_bias=0.14,
            tags=["earnings", "ai"],
            content_hash=hash_content("NVDA", "seed", "earnings"),
        ),
        NormalizedEventCandidate(
            symbol="AAPL",
            event_type="product_launch",
            headline="Apple unveils upgraded silicon roadmap and on-device AI features",
            summary="The launch expands the installed base monetization narrative and device refresh case.",
            thesis="Product roadmap supports premium mix and refresh-cycle optimism.",
            source_label="Manual Analyst Entry",
            source_type="manual",
            source_url="",
            occurred_at=now - timedelta(days=2),
            directional_bias=0.08,
            tags=["launch", "ai"],
            content_hash=hash_content("AAPL", "seed", "launch"),
        ),
        NormalizedEventCandidate(
            symbol="TSLA",
            event_type="regulatory",
            headline="Tesla faces another regulatory probe tied to autonomous driving disclosures",
            summary="The headline increases execution and multiple-compression risk in the near term.",
            thesis="Regulatory overhang can pressure sentiment despite long-term growth optionality.",
            source_label="Manual Analyst Entry",
            source_type="manual",
            source_url="",
            occurred_at=now - timedelta(days=2),
            directional_bias=-0.16,
            tags=["probe", "autonomy"],
            content_hash=hash_content("TSLA", "seed", "regulatory"),
        ),
        NormalizedEventCandidate(
            symbol="AMD",
            event_type="customer_win",
            headline="AMD secures additional hyperscaler accelerator design wins",
            summary="The win suggests continued GPU share gains in AI infrastructure workloads.",
            thesis="Incremental hyperscaler design wins improve the revenue mix and confidence in share gains.",
            source_label="Manual Analyst Entry",
            source_type="manual",
            source_url="",
            occurred_at=now - timedelta(days=1),
            directional_bias=0.11,
            tags=["customer_win"],
            content_hash=hash_content("AMD", "seed", "customer_win"),
        ),
    ]
    for candidate in seeded_candidates:
        create_event(session, symbol=candidate.symbol, candidate=candidate)
    for security in list_reference_universe(session):
        security.last_price = SAMPLE_PRICE_MAP.get(security.symbol, 100.0)
        security.day_change_pct = 0.8 if security.symbol in {"NVDA", "AAPL", "AMD"} else -0.9 if security.symbol == "TSLA" else 0.3
        security.last_price_at = now
        session.add(security)
    session.commit()
    for security in list_reference_universe(session):
        rebuild_security_recommendation(session, settings, security)
    backtest = refresh_backtest(session)
    update_connector_state(
        session,
        "market_refresh",
        status="seeded",
        last_polled_at=now,
        metadata={"seeded_demo_content": True, "backtest_run_id": backtest.id},
    )
