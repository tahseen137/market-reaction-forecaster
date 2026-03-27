from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.data_sources import FinnhubClient, NormalizedEventCandidate, RssFeedClient, SecEdgarClient, TwelveDataClient, hash_content
from app.models import (
    BacktestRun,
    ConnectorState,
    Event,
    PortfolioPosition,
    RecommendationSnapshot,
    Security,
    SourceSnapshot,
    SubscriptionState,
    User,
    UserRecommendation,
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


def rebuild_security_recommendation(session: Session, settings: Settings, security: Security) -> RecommendationSnapshot:
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
        source_status=base.source_status,
        thesis_summary=base.thesis_summary,
        evidence_summary=base.evidence_summary,
        invalidation_conditions=base.invalidation_conditions,
        factor_scores=base.factor_scores,
        horizon_ranges=base.horizon_ranges,
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
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
        "latest_event_id": snapshot.latest_event_id,
        "factor_scores": snapshot.factor_scores,
        "horizon_ranges": snapshot.horizon_ranges,
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
            horizon_days=20,
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
    for security in list_reference_universe(session):
        refresh_security_quote(session, settings, security)
        created_events += ingest_candidate_events(session, settings, security)
        rebuild_security_recommendation(session, settings, security)
        refreshed_symbols.append(security.symbol)
    rebuild_all_user_recommendations(session)
    backtest = refresh_backtest(session)
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
        },
    )


def seed_demo_content(session: Session, settings: Settings) -> None:
    refresh_runtime_connector_states(session, settings)
    if session.scalars(select(Event).limit(1)).first():
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
