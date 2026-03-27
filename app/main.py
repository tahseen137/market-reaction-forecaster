from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Generator
from uuid import uuid4

import sentry_sdk
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.activity_service import list_activity_events, record_activity
from app.auth import (
    auth_required,
    clear_session,
    csrf_token_matches,
    current_session_user_id,
    ensure_csrf_token,
    is_authenticated,
    login_redirect,
    refresh_session_from_user,
    sanitize_next_path,
    set_authenticated_user_session,
)
from app.billing import create_checkout_session, create_portal_session, handle_webhook_event
from app.config import Settings, get_settings
from app.db import DatabaseState, build_database_state, database_is_ready, init_database
from app.models import BacktestRun, Event, User
from app.notifications import send_password_reset_email
from app.reporting import build_backtest_markdown, build_recommendation_markdown
from app.schemas import (
    ActivityEventRead,
    BacktestRunRead,
    BillingRequest,
    ChangePasswordRequest,
    ConnectorStatusRead,
    CurrentUserResponse,
    DashboardRead,
    EventCreate,
    EventRead,
    ForgotPasswordRequest,
    ModelPortfolioRead,
    PermissionSummary,
    RecommendationDetailRead,
    RecommendationFeedEntry,
    ResetPasswordRequest,
    SecurityRead,
    SessionLoginRequest,
    SessionSignupRequest,
    SessionStatusResponse,
    SubscriptionRead,
    SystemStatusRead,
    UserCreateRequest,
    UserProfileRead,
    UserProfileWrite,
    UserRead,
    UserUpdateRequest,
    WatchlistCreate,
    WatchlistRead,
)
from app.services import (
    build_dashboard,
    build_model_portfolio,
    build_system_status,
    create_event,
    create_watchlist,
    default_profile_payload,
    get_event,
    get_latest_backtest,
    get_recommendation_detail,
    get_recommendation_feed,
    list_events,
    list_reference_universe,
    list_watchlists,
    rebuild_all_user_recommendations,
    rebuild_model_portfolio_for_user,
    rebuild_security_recommendation,
    rebuild_user_recommendations_for_user,
    refresh_backtest,
    refresh_market_state,
    refresh_security_quote,
    seed_demo_content,
    seed_universe,
)
from app.templates_context import page_context
from app.user_service import (
    acknowledge_disclosures,
    authenticate_user,
    can_manage_users,
    change_password,
    create_or_update_profile,
    create_user,
    ensure_bootstrap_admin,
    get_subscription_state,
    get_user_by_email,
    get_user_by_id,
    has_paid_access,
    issue_password_reset_token,
    list_users,
    reset_password_with_token,
    update_user,
)


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _current_user_response(user: User | None) -> CurrentUserResponse | None:
    return CurrentUserResponse.model_validate(user) if user else None


def _subscription_read(user: User | None) -> SubscriptionRead | None:
    if user is None or user.subscription_state is None:
        return None
    return SubscriptionRead.model_validate(user.subscription_state)


def _permission_summary(user: User | None, settings: Settings) -> PermissionSummary:
    return PermissionSummary(
        can_manage_users=can_manage_users(user),
        has_paid_access=has_paid_access(user),
        billing_enabled=settings.billing_enabled,
    )


def _session_status(request: Request, user: User | None, settings: Settings, *, next_path: str | None = "/") -> SessionStatusResponse:
    authenticated = is_authenticated(request, user)
    csrf_token = ensure_csrf_token(request) if authenticated else None
    return SessionStatusResponse(
        auth_required=auth_required(request),
        authenticated=authenticated,
        next_path=sanitize_next_path(next_path),
        csrf_token=csrf_token,
        current_user=_current_user_response(user),
        subscription=_subscription_read(user),
        permissions=_permission_summary(user, settings),
    )


def _security_read(security) -> SecurityRead:
    return SecurityRead.model_validate(security)


def _watchlist_read(watchlist) -> WatchlistRead:
    return WatchlistRead(
        id=watchlist.id,
        name=watchlist.name,
        symbols=[link.security.symbol for link in watchlist.securities],
        created_at=watchlist.created_at,
        updated_at=watchlist.updated_at,
    )


def _event_read(event: Event) -> EventRead:
    return EventRead(
        id=event.id,
        symbol=event.security.symbol,
        event_type=event.event_type,
        headline=event.headline,
        summary=event.summary,
        thesis=event.thesis,
        source_label=event.source_label,
        occurred_at=event.occurred_at,
        directional_bias=event.directional_bias,
        is_material=event.is_material,
        tags=list(event.tags),
        source_snapshot=event.source_snapshot,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _activity_read(item) -> ActivityEventRead:
    return ActivityEventRead.model_validate(item)


def _user_read(user: User) -> UserRead:
    return UserRead.model_validate(user)


def _dashboard_read(data: dict[str, Any]) -> DashboardRead:
    return DashboardRead.model_validate(data | {"top_recommendations": [RecommendationFeedEntry.model_validate(item) for item in data["top_recommendations"]]})


def _backtest_read(run: BacktestRun) -> BacktestRunRead:
    return BacktestRunRead.model_validate(run)


def _system_status_read(data: dict[str, Any]) -> SystemStatusRead:
    return SystemStatusRead.model_validate(
        data | {"connectors": [ConnectorStatusRead.model_validate(item) for item in data["connectors"]]}
    )


def _require_csrf(request: Request) -> None:
    if auth_required(request) and not csrf_token_matches(request, request.headers.get("X-CSRF-Token")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token is invalid")


def _billing_urls(request: Request) -> tuple[str, str, str]:
    base = str(request.base_url).rstrip("/")
    return (f"{base}/account?checkout=success", f"{base}/pricing?checkout=cancelled", f"{base}/account")


def _payload(request: Request, settings: Settings, user: User | None, *, page: str, title: str, body_class: str = "app-shell", **data: Any) -> dict[str, Any]:
    payload = page_context(
        request=request,
        settings=settings,
        user=user,
        page=page,
        title=title,
        body_class=body_class,
        session_status=_session_status(request, user, settings, next_path=request.url.path),
        **data,
    )
    payload["page_data_json"] = json.dumps(payload.get("page_data", {}), default=_json_default)
    return payload


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    database_state = build_database_state(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if resolved_settings.sentry_dsn:
            sentry_sdk.init(dsn=resolved_settings.sentry_dsn, environment=resolved_settings.app_env)
        init_database(database_state, auto_create_schema=resolved_settings.auto_create_schema)
        app.state.settings = resolved_settings
        app.state.database = database_state
        with database_state.session_factory() as session:
            admin_user = ensure_bootstrap_admin(session, resolved_settings)
            seed_universe(session)
            seed_demo_content(session, resolved_settings)
            if admin_user is not None:
                if admin_user.profile is None:
                    create_or_update_profile(session, admin_user, default_profile_payload())
                if admin_user.disclosures_acknowledged_at is None:
                    acknowledge_disclosures(session, admin_user)
                rebuild_user_recommendations_for_user(session, admin_user)
                rebuild_model_portfolio_for_user(session, admin_user)
            rebuild_all_user_recommendations(session)
            refresh_backtest(session)
            build_system_status(session, resolved_settings)
            app.state.auth_required = bool(list_users(session))
        yield
        database_state.engine.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="0.1.0", lifespan=lifespan)
    if resolved_settings.enable_gzip:
        app.add_middleware(GZipMiddleware, minimum_size=500)
    if resolved_settings.session_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=resolved_settings.session_secret,
            session_cookie="market_reaction_forecaster_session",
            same_site="lax",
            https_only=resolved_settings.session_https_only,
            max_age=resolved_settings.session_max_age_seconds,
        )
    if resolved_settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_hosts)
    if resolved_settings.enforce_https:
        app.add_middleware(HTTPSRedirectMiddleware)

    @app.middleware("http")
    async def add_response_headers(request: Request, call_next):
        request_id = uuid4().hex
        started_at = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        if request.url.path in {"/", "/pricing", "/login", "/signup"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def get_database_state(request: Request) -> DatabaseState:
        return request.app.state.database  # type: ignore[return-value]

    def get_runtime_settings(request: Request) -> Settings:
        return request.app.state.settings  # type: ignore[return-value]

    def get_session(database: DatabaseState = Depends(get_database_state)) -> Generator[Session, None, None]:
        db_session = database.session_factory()
        try:
            yield db_session
        finally:
            db_session.close()

    def get_current_user(request: Request, session: Session = Depends(get_session)) -> User | None:
        if not auth_required(request):
            return None
        user_id = current_session_user_id(request)
        if not user_id:
            return None
        user = get_user_by_id(session, user_id)
        if user is None or not user.is_active:
            clear_session(request)
            return None
        refresh_session_from_user(request, user)
        return user

    def require_authenticated_api(current_user: User | None = Depends(get_current_user)) -> User:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        return current_user

    def require_paid_api(current_user: User = Depends(require_authenticated_api)) -> User:
        if not has_paid_access(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upgrade required")
        return current_user

    def require_disclosed_paid_api(current_user: User = Depends(require_paid_api)) -> User:
        if current_user.disclosures_acknowledged_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Disclosures must be acknowledged first")
        return current_user

    def require_admin_api(current_user: User = Depends(require_authenticated_api)) -> User:
        if not can_manage_users(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        return current_user

    def require_page_user(request: Request, current_user: User | None = Depends(get_current_user)) -> User:
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": login_redirect(request.url.path)})
        return current_user

    @app.exception_handler(HTTPException)
    async def html_redirect_handler(request: Request, exc: HTTPException):
        if exc.status_code == status.HTTP_303_SEE_OTHER and exc.headers and "Location" in exc.headers:
            return RedirectResponse(url=exc.headers["Location"], status_code=status.HTTP_303_SEE_OTHER)
        return await http_exception_handler(request, exc)

    @app.get("/health", response_class=PlainTextResponse)
    def health() -> str:
        return "ok"

    @app.get("/ready", response_class=PlainTextResponse)
    def ready(database: DatabaseState = Depends(get_database_state)) -> str:
        if not database_is_ready(database):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
        return "ready"

    @app.get("/", response_class=HTMLResponse)
    def landing(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User | None = Depends(get_current_user),
    ) -> HTMLResponse:
        feed = [RecommendationFeedEntry.model_validate(item) for item in get_recommendation_feed(session)]
        backtest = _backtest_read(get_latest_backtest(session))
        return templates.TemplateResponse(
            request,
            "landing.html",
            _payload(
                request,
                settings,
                current_user,
                page="landing",
                title="AI-powered buy, hold, and sell calls for large-cap tech",
                body_class="landing-shell",
                page_data={"feed": [item.model_dump(mode="json") for item in feed], "backtest": backtest.model_dump(mode="json")},
                sample_feed=feed,
                backtest=backtest,
            ),
        )

    @app.get("/pricing", response_class=HTMLResponse)
    def pricing_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User | None = Depends(get_current_user),
    ) -> HTMLResponse:
        backtest = _backtest_read(get_latest_backtest(session))
        return templates.TemplateResponse(
            request,
            "pricing.html",
            _payload(
                request,
                settings,
                current_user,
                page="pricing",
                title="Pricing",
                body_class="landing-shell",
                page_data={"backtest": backtest.model_dump(mode="json")},
                backtest=backtest,
            ),
        )

    @app.get("/legal", response_class=HTMLResponse)
    def legal_page(request: Request, settings: Settings = Depends(get_runtime_settings), current_user: User | None = Depends(get_current_user)) -> HTMLResponse:
        return templates.TemplateResponse(request, "legal.html", _payload(request, settings, current_user, page="legal", title="Legal and risk disclosures", body_class="landing-shell", page_data={}))

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, settings: Settings = Depends(get_runtime_settings), current_user: User | None = Depends(get_current_user)) -> HTMLResponse:
        if current_user is not None:
            return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(request, "auth.html", _payload(request, settings, current_user, page="login", title="Log in", body_class="auth-shell", mode="login", page_data={"next_path": sanitize_next_path(request.query_params.get("next"))}))

    @app.get("/signup", response_class=HTMLResponse)
    def signup_page(request: Request, settings: Settings = Depends(get_runtime_settings), current_user: User | None = Depends(get_current_user)) -> HTMLResponse:
        if current_user is not None:
            return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(request, "auth.html", _payload(request, settings, current_user, page="signup", title="Create your account", body_class="auth-shell", mode="signup", page_data={}))

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        unlocked = has_paid_access(current_user) and current_user.disclosures_acknowledged_at is not None
        feed_user = current_user if unlocked else None
        dashboard = _dashboard_read(build_dashboard(session, feed_user))
        feed = [RecommendationFeedEntry.model_validate(item) for item in get_recommendation_feed(session, user=feed_user)]
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="dashboard",
                title="Dashboard",
                dashboard=dashboard,
                feed=feed[:12],
                access_state="full" if unlocked else "upgrade" if not has_paid_access(current_user) else "disclosures",
                page_data={"dashboard": dashboard.model_dump(mode="json"), "feed": [item.model_dump(mode="json") for item in feed[:12]]},
            ),
        )

    @app.get("/watchlists", response_class=HTMLResponse)
    def watchlists_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        watchlists = [_watchlist_read(item) for item in (list_watchlists(session, current_user) if has_paid_access(current_user) else [])]
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="watchlists",
                title="Watchlists",
                watchlists=watchlists,
                universe=[_security_read(item) for item in list_reference_universe(session)],
                access_state="full" if has_paid_access(current_user) and current_user.disclosures_acknowledged_at else "upgrade",
                page_data={"watchlists": [item.model_dump(mode="json") for item in watchlists]},
            ),
        )

    @app.get("/events", response_class=HTMLResponse)
    def events_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        events = [_event_read(item) for item in list_events(session, limit=40)]
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(request, settings, current_user, page="events", title="Events", events=events, page_data={"events": [item.model_dump(mode="json") for item in events]}),
        )

    @app.get("/events/{event_id}", response_class=HTMLResponse)
    def event_detail_page(
        event_id: str,
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        event = get_event(session, event_id)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
        event_read = _event_read(event)
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(request, settings, current_user, page="event-detail", title=event.headline, event=event_read, page_data={"event": event_read.model_dump(mode="json")}),
        )

    @app.get("/recommendations/{symbol}", response_class=HTMLResponse)
    def recommendation_page(
        symbol: str,
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        detail = get_recommendation_detail(session, symbol, user=current_user if has_paid_access(current_user) else None)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        recommendation = RecommendationDetailRead.model_validate(detail)
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="recommendation-detail",
                title=f"{symbol.upper()} recommendation",
                recommendation=recommendation,
                access_state="full" if has_paid_access(current_user) and current_user.disclosures_acknowledged_at else "upgrade",
                page_data={"recommendation": recommendation.model_dump(mode="json")},
            ),
        )

    @app.get("/backtests", response_class=HTMLResponse)
    def backtests_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        backtest = _backtest_read(get_latest_backtest(session))
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="backtests",
                title="Backtests",
                backtest=backtest,
                access_state="full" if has_paid_access(current_user) and current_user.disclosures_acknowledged_at else "upgrade",
                page_data={"backtest": backtest.model_dump(mode="json")},
            ),
        )

    @app.get("/paper-portfolio", response_class=HTMLResponse)
    def portfolio_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        portfolio = ModelPortfolioRead.model_validate(build_model_portfolio(session, current_user))
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="portfolio",
                title="Model portfolio",
                portfolio=portfolio,
                access_state="full" if has_paid_access(current_user) and current_user.disclosures_acknowledged_at else "upgrade",
                page_data={"portfolio": portfolio.model_dump(mode="json")},
            ),
        )

    @app.get("/account", response_class=HTMLResponse)
    def account_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        profile = UserProfileRead.model_validate(current_user.profile) if current_user.profile else None
        subscription = _subscription_read(current_user)
        activity = [
            _activity_read(item)
            for item in list_activity_events(
                session,
                limit=25,
                actor_user_id=None if can_manage_users(current_user) else current_user.id,
            )
        ]
        system_status = _system_status_read(build_system_status(session, settings))
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="account",
                title="Account",
                profile=profile,
                subscription=subscription,
                system_status=system_status,
                activity=activity,
                page_data={
                    "profile": profile.model_dump(mode="json") if profile else None,
                    "subscription": subscription.model_dump(mode="json") if subscription else None,
                    "system_status": system_status.model_dump(mode="json"),
                    "activity": [item.model_dump(mode="json") for item in activity],
                },
            ),
        )

    @app.get("/admin/users", response_class=HTMLResponse)
    def admin_users_page(
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
        current_user: User = Depends(require_page_user),
    ) -> HTMLResponse:
        if not can_manage_users(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        users = [_user_read(user) for user in list_users(session)]
        activity = [_activity_read(item) for item in list_activity_events(session, limit=40)]
        return templates.TemplateResponse(
            request,
            "app.html",
            _payload(
                request,
                settings,
                current_user,
                page="admin-users",
                title="Admin users",
                users=users,
                activity=activity,
                page_data={"users": [item.model_dump(mode="json") for item in users], "activity": [item.model_dump(mode="json") for item in activity]},
            ),
        )

    @app.get("/api/session", response_model=SessionStatusResponse)
    def session_status_api(request: Request, settings: Settings = Depends(get_runtime_settings), current_user: User | None = Depends(get_current_user)) -> SessionStatusResponse:
        return _session_status(request, current_user, settings)

    @app.post("/api/session/signup", response_model=SessionStatusResponse, status_code=status.HTTP_201_CREATED)
    def signup_api(
        payload: SessionSignupRequest,
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
    ) -> SessionStatusResponse:
        try:
            user = create_user(session, username=payload.username, email=payload.email, password=payload.password, full_name=payload.full_name, settings=settings)
            create_or_update_profile(session, user, default_profile_payload())
            rebuild_user_recommendations_for_user(session, user)
            rebuild_model_portfolio_for_user(session, user)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        set_authenticated_user_session(request, user)
        record_activity(session, actor=user, action="user.signup", entity_type="user", entity_id=user.id, description=f"{user.username} created an account", details={"plan": "pro_trial"})
        return _session_status(request, user, settings)

    @app.post("/api/session/login", response_model=SessionStatusResponse)
    def login_api(
        payload: SessionLoginRequest,
        request: Request,
        session: Session = Depends(get_session),
        settings: Settings = Depends(get_runtime_settings),
    ) -> SessionStatusResponse:
        result = authenticate_user(session, payload.username, payload.password, settings)
        if result.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=result.error or "Invalid credentials")
        user = result.user
        set_authenticated_user_session(request, user)
        record_activity(session, actor=user, action="session.login", entity_type="user", entity_id=user.id, description=f"{user.username} logged in", details={"source": "web"})
        return _session_status(request, user, settings, next_path=payload.next_path)

    @app.post("/api/session/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout_api(request: Request, session: Session = Depends(get_session), current_user: User | None = Depends(get_current_user)) -> Response:
        _require_csrf(request)
        if current_user is not None:
            record_activity(session, actor=current_user, action="session.logout", entity_type="user", entity_id=current_user.id, description=f"{current_user.username} logged out", details={})
        clear_session(request)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/session/forgot-password")
    def forgot_password_api(payload: ForgotPasswordRequest, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)) -> dict[str, object]:
        user = get_user_by_email(session, payload.email)
        debug_token: str | None = None
        if settings.app_env != "test" and not settings.password_reset_email_enabled:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Password reset email is not configured")
        if user is not None:
            debug_token = issue_password_reset_token(session, user)
            if settings.app_env != "test":
                reset_url = f"{settings.site_url.rstrip('/')}/login?reset_token={debug_token}"
                try:
                    send_password_reset_email(settings, user, reset_url=reset_url)
                except Exception as exc:
                    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Password reset email delivery failed") from exc
            record_activity(session, actor=user, action="session.password_reset_requested", entity_type="user", entity_id=user.id, description=f"{user.username} requested a password reset", details={})
        response: dict[str, object] = {"status": "ok"}
        if settings.app_env == "test":
            response["debug_token"] = debug_token
        return response

    @app.post("/api/session/reset-password")
    def reset_password_api(payload: ResetPasswordRequest, session: Session = Depends(get_session)) -> dict[str, str]:
        try:
            user = reset_password_with_token(session, payload.token, payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        record_activity(session, actor=user, action="session.password_reset_completed", entity_type="user", entity_id=user.id, description=f"{user.username} reset the account password", details={})
        return {"status": "ok"}

    @app.get("/api/profile", response_model=UserProfileRead)
    def get_profile_api(current_user: User = Depends(require_authenticated_api)) -> UserProfileRead:
        if current_user.profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
        return UserProfileRead.model_validate(current_user.profile)

    @app.post("/api/profile", response_model=UserProfileRead)
    def create_profile_api(payload: UserProfileWrite, request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_authenticated_api)) -> UserProfileRead:
        _require_csrf(request)
        profile = create_or_update_profile(session, current_user, payload.model_dump())
        rebuild_user_recommendations_for_user(session, current_user)
        rebuild_model_portfolio_for_user(session, current_user)
        record_activity(session, actor=current_user, action="profile.updated", entity_type="user_profile", entity_id=profile.id, description=f"{current_user.username} updated onboarding preferences", details=payload.model_dump())
        return UserProfileRead.model_validate(profile)

    @app.patch("/api/profile", response_model=UserProfileRead)
    def patch_profile_api(payload: UserProfileWrite, request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_authenticated_api)) -> UserProfileRead:
        return create_profile_api(payload, request, session, current_user)

    @app.post("/api/profile/acknowledge-disclosures", response_model=SessionStatusResponse)
    def acknowledge_disclosures_api(request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings), current_user: User = Depends(require_authenticated_api)) -> SessionStatusResponse:
        _require_csrf(request)
        acknowledge_disclosures(session, current_user)
        rebuild_user_recommendations_for_user(session, current_user)
        rebuild_model_portfolio_for_user(session, current_user)
        record_activity(session, actor=current_user, action="profile.disclosures_acknowledged", entity_type="user", entity_id=current_user.id, description=f"{current_user.username} acknowledged research and risk disclosures", details={})
        return _session_status(request, current_user, settings)

    @app.get("/api/account/subscription", response_model=SubscriptionRead)
    def subscription_api(current_user: User = Depends(require_authenticated_api)) -> SubscriptionRead:
        subscription = _subscription_read(current_user)
        if subscription is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        return subscription

    @app.post("/api/account/change-password")
    def change_password_api(payload: ChangePasswordRequest, request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_authenticated_api)) -> dict[str, str]:
        _require_csrf(request)
        try:
            change_password(session, current_user, current_password=payload.current_password, new_password=payload.new_password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        record_activity(session, actor=current_user, action="account.password_changed", entity_type="user", entity_id=current_user.id, description=f"{current_user.username} changed the account password", details={})
        return {"status": "ok"}

    @app.get("/api/system/status", response_model=SystemStatusRead)
    def system_status_api(session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings), current_user: User = Depends(require_authenticated_api)) -> SystemStatusRead:
        return _system_status_read(build_system_status(session, settings))

    @app.post("/api/billing/create-checkout-session")
    def create_checkout_session_api(payload: BillingRequest, request: Request, current_user: User = Depends(require_authenticated_api), settings: Settings = Depends(get_runtime_settings)) -> dict[str, str]:
        _require_csrf(request)
        success_url, cancel_url, _ = _billing_urls(request)
        try:
            url = create_checkout_session(settings, current_user, billing_cycle=payload.billing_cycle, success_url=success_url, cancel_url=cancel_url)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return {"url": url}

    @app.post("/api/billing/create-portal-session")
    def create_portal_session_api(request: Request, current_user: User = Depends(require_authenticated_api), settings: Settings = Depends(get_runtime_settings)) -> dict[str, str]:
        _require_csrf(request)
        _, _, return_url = _billing_urls(request)
        try:
            url = create_portal_session(settings, get_subscription_state(current_user), return_url=return_url)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return {"url": url}

    @app.post("/api/billing/webhook")
    async def stripe_webhook_api(request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)) -> dict[str, str]:
        payload = await request.body()
        try:
            return handle_webhook_event(session, settings, payload=payload, signature=request.headers.get("Stripe-Signature"))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/api/reference/universe", response_model=list[SecurityRead])
    def reference_universe_api(session: Session = Depends(get_session)) -> list[SecurityRead]:
        return [_security_read(item) for item in list_reference_universe(session)]

    @app.get("/api/recommendations/feed", response_model=list[RecommendationFeedEntry])
    def recommendation_feed_api(session: Session = Depends(get_session), current_user: User | None = Depends(get_current_user)) -> list[RecommendationFeedEntry]:
        if current_user is not None and has_paid_access(current_user) and current_user.disclosures_acknowledged_at is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Disclosures must be acknowledged first")
        feed = get_recommendation_feed(session, user=current_user if current_user is not None and has_paid_access(current_user) else None)
        return [RecommendationFeedEntry.model_validate(item) for item in feed]

    @app.get("/api/recommendations/{symbol}", response_model=RecommendationDetailRead)
    def recommendation_detail_api(symbol: str, session: Session = Depends(get_session), current_user: User = Depends(require_disclosed_paid_api)) -> RecommendationDetailRead:
        detail = get_recommendation_detail(session, symbol, user=current_user)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        return RecommendationDetailRead.model_validate(detail)

    @app.get("/api/recommendations/{symbol}/report.md", response_class=PlainTextResponse)
    def recommendation_report_api(symbol: str, session: Session = Depends(get_session), current_user: User = Depends(require_disclosed_paid_api)) -> str:
        detail = get_recommendation_detail(session, symbol, user=current_user)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
        return build_recommendation_markdown(RecommendationDetailRead.model_validate(detail))

    @app.get("/api/events", response_model=list[EventRead])
    def events_api(session: Session = Depends(get_session)) -> list[EventRead]:
        return [_event_read(item) for item in list_events(session, limit=50)]

    @app.get("/api/events/{event_id}", response_model=EventRead)
    def event_api(event_id: str, session: Session = Depends(get_session)) -> EventRead:
        event = get_event(session, event_id)
        if event is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
        return _event_read(event)

    @app.post("/api/events", response_model=EventRead, status_code=status.HTTP_201_CREATED)
    def create_event_api(payload: EventCreate, request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings), current_user: User = Depends(require_admin_api)) -> EventRead:
        _require_csrf(request)
        from app.data_sources import NormalizedEventCandidate, hash_content

        candidate = NormalizedEventCandidate(
            symbol=payload.symbol.strip().upper(),
            event_type=payload.event_type,
            headline=payload.headline,
            summary=payload.summary,
            thesis=payload.thesis or payload.summary or payload.headline,
            source_label=payload.source_label,
            source_type="manual",
            source_url=payload.source_url,
            occurred_at=_now(),
            directional_bias=payload.directional_bias,
            tags=["manual"],
            content_hash=hash_content(payload.symbol, payload.event_type, payload.headline, payload.source_url or "manual"),
        )
        try:
            event = create_event(session, symbol=payload.symbol, candidate=candidate)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        refresh_security_quote(session, settings, event.security)
        rebuild_security_recommendation(session, settings, event.security)
        rebuild_all_user_recommendations(session)
        refresh_backtest(session)
        record_activity(session, actor=current_user, action="event.created", entity_type="event", entity_id=event.id, description=f"{current_user.username} created a manual event for {event.security.symbol}", details={"symbol": event.security.symbol, "event_type": event.event_type})
        return _event_read(event)

    @app.get("/api/watchlists", response_model=list[WatchlistRead])
    def watchlists_api(current_user: User = Depends(require_disclosed_paid_api), session: Session = Depends(get_session)) -> list[WatchlistRead]:
        return [_watchlist_read(item) for item in list_watchlists(session, current_user)]

    @app.post("/api/watchlists", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
    def create_watchlist_api(payload: WatchlistCreate, request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_disclosed_paid_api)) -> WatchlistRead:
        _require_csrf(request)
        watchlist = create_watchlist(session, current_user, name=payload.name, symbols=payload.symbols)
        record_activity(session, actor=current_user, action="watchlist.created", entity_type="watchlist", entity_id=watchlist.id, description=f"{current_user.username} created watchlist {watchlist.name}", details={"symbols": payload.symbols})
        return _watchlist_read(watchlist)

    @app.get("/api/backtests/summary", response_model=BacktestRunRead)
    def backtest_summary_api(session: Session = Depends(get_session)) -> BacktestRunRead:
        return _backtest_read(get_latest_backtest(session))

    @app.get("/api/backtests/{run_id}", response_model=BacktestRunRead)
    def backtest_detail_api(run_id: str, session: Session = Depends(get_session)) -> BacktestRunRead:
        run = session.get(BacktestRun, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
        return _backtest_read(run)

    @app.get("/api/backtests/{run_id}/report.md", response_class=PlainTextResponse)
    def backtest_report_api(run_id: str, session: Session = Depends(get_session)) -> str:
        run = session.get(BacktestRun, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found")
        return build_backtest_markdown(_backtest_read(run))

    @app.get("/api/model-portfolio", response_model=ModelPortfolioRead)
    def model_portfolio_api(session: Session = Depends(get_session), current_user: User = Depends(require_disclosed_paid_api)) -> ModelPortfolioRead:
        return ModelPortfolioRead.model_validate(build_model_portfolio(session, current_user))

    @app.post("/api/model-portfolio/rebuild", response_model=ModelPortfolioRead)
    def rebuild_portfolio_api(request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_disclosed_paid_api)) -> ModelPortfolioRead:
        _require_csrf(request)
        rebuild_model_portfolio_for_user(session, current_user)
        record_activity(session, actor=current_user, action="portfolio.rebuilt", entity_type="portfolio", entity_id=current_user.id, description=f"{current_user.username} rebuilt the model portfolio", details={})
        return ModelPortfolioRead.model_validate(build_model_portfolio(session, current_user))

    @app.get("/api/activity", response_model=list[ActivityEventRead])
    def activity_api(session: Session = Depends(get_session), current_user: User = Depends(require_admin_api)) -> list[ActivityEventRead]:
        return [_activity_read(item) for item in list_activity_events(session, limit=75)]

    @app.get("/api/admin/users", response_model=list[UserRead])
    def admin_users_api(session: Session = Depends(get_session), current_user: User = Depends(require_admin_api)) -> list[UserRead]:
        return [_user_read(user) for user in list_users(session)]

    @app.post("/api/admin/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
    def create_admin_user_api(payload: UserCreateRequest, request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings), current_user: User = Depends(require_admin_api)) -> UserRead:
        _require_csrf(request)
        try:
            user = create_user(
                session,
                username=payload.username,
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
                role=payload.role,
                email_verified=True,
                start_trial=payload.role != "admin",
                settings=settings,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if payload.role == "subscriber":
            subscription = get_subscription_state(user)
            subscription.plan_key = "manual_grant"
            subscription.status = "active"
            session.add(subscription)
            session.commit()
            session.refresh(user)
        record_activity(session, actor=current_user, action="admin.user_created", entity_type="user", entity_id=user.id, description=f"{current_user.username} created {user.username}", details={"role": payload.role})
        return _user_read(user)

    @app.patch("/api/admin/users/{user_id}", response_model=UserRead)
    def update_admin_user_api(user_id: str, payload: UserUpdateRequest, request: Request, session: Session = Depends(get_session), current_user: User = Depends(require_admin_api)) -> UserRead:
        _require_csrf(request)
        target = get_user_by_id(session, user_id)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        try:
            target = update_user(
                session,
                target,
                full_name=payload.full_name,
                email=payload.email,
                role=payload.role,
                is_active=payload.is_active,
                password=payload.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        record_activity(session, actor=current_user, action="admin.user_updated", entity_type="user", entity_id=target.id, description=f"{current_user.username} updated {target.username}", details=payload.model_dump(exclude_none=True))
        return _user_read(target)

    @app.post("/api/admin/refresh-market")
    def refresh_market_api(request: Request, session: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings), current_user: User = Depends(require_admin_api)) -> dict[str, str]:
        _require_csrf(request)
        refresh_market_state(session, settings)
        record_activity(session, actor=current_user, action="admin.market_refreshed", entity_type="system", entity_id=None, description=f"{current_user.username} refreshed market state", details={})
        return {"status": "ok"}

    return app


app = create_app()
