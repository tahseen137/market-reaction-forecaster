from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SubscriptionState, User, UserProfile
from app.security import hash_password, verify_password


ADMIN_ROLES = {"admin"}


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def count_users(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(User)) or 0)


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    statement = select(User).where(User.username == normalize_username(username))
    return session.scalars(statement).first()


def get_user_by_email(session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == normalize_email(email))
    return session.scalars(statement).first()


def list_users(session: Session) -> list[User]:
    statement = select(User).order_by(User.created_at.asc(), User.username.asc())
    return list(session.scalars(statement))


def get_subscription_state(user: User) -> SubscriptionState:
    if user.subscription_state is None:
        raise ValueError("User subscription state has not been initialized")
    return user.subscription_state


def has_paid_access(user: User | None) -> bool:
    if user is None:
        return False
    if user.role == "admin":
        return True
    subscription = user.subscription_state
    if subscription is None:
        return False
    if subscription.status == "active":
        return True
    if subscription.status == "trialing":
        trial_end = _coerce_utc(subscription.trial_ends_at)
        return bool(trial_end and trial_end > _now())
    return False


def can_manage_users(user: User | None) -> bool:
    return bool(user and user.role in ADMIN_ROLES)


def sync_role_with_subscription(user: User) -> None:
    if user.role == "admin":
        return
    user.role = "subscriber" if has_paid_access(user) else "trial_user"


def create_user(
    session: Session,
    *,
    username: str,
    email: str,
    password: str,
    full_name: str = "",
    role: str = "trial_user",
    email_verified: bool = False,
    start_trial: bool = True,
    settings: Settings | None = None,
) -> User:
    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    if get_user_by_username(session, normalized_username):
        raise ValueError("A user with that username already exists")
    if get_user_by_email(session, normalized_email):
        raise ValueError("A user with that email already exists")

    now = _now()
    trial_end = now + timedelta(days=settings.trial_days if settings else 7)
    user = User(
        username=normalized_username,
        email=normalized_email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        role=role,
        email_verified=email_verified,
        email_verification_token=token_urlsafe(24) if not email_verified else None,
    )
    subscription = SubscriptionState(
        user=user,
        plan_key="pro_trial" if start_trial else "free",
        status="trialing" if start_trial else "free",
        trial_started_at=now if start_trial else None,
        trial_ends_at=trial_end if start_trial else None,
    )
    session.add_all([user, subscription])
    session.commit()
    session.refresh(user)
    return user


def ensure_bootstrap_admin(session: Session, settings: Settings) -> User | None:
    if not settings.bootstrap_admin_configured:
        return None
    existing_user = get_user_by_username(session, settings.bootstrap_admin_username or "")
    if existing_user:
        return existing_user
    user = create_user(
        session,
        username=settings.bootstrap_admin_username or "admin",
        email=settings.bootstrap_admin_email or "admin@marketreactionforecaster.local",
        password=settings.bootstrap_admin_password or "",
        full_name="Market Reaction Forecaster Admin",
        role="admin",
        email_verified=True,
        start_trial=False,
        settings=settings,
    )
    subscription = get_subscription_state(user)
    subscription.plan_key = "admin"
    subscription.status = "active"
    subscription.current_period_end = None
    session.add_all([user, subscription])
    session.commit()
    session.refresh(user)
    return user


def update_user(
    session: Session,
    user: User,
    *,
    full_name: str | None = None,
    email: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    if full_name is not None:
        user.full_name = full_name.strip()
    if email is not None:
        normalized_email = normalize_email(email)
        existing = session.scalars(select(User).where(User.email == normalized_email, User.id != user.id)).first()
        if existing:
            raise ValueError("A user with that email already exists")
        user.email = normalized_email
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if password:
        user.password_hash = hash_password(password)
        user.failed_login_attempts = 0
        user.locked_until = None
        user.password_reset_token = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_or_update_profile(session: Session, user: User, payload: dict[str, str]) -> UserProfile:
    profile = user.profile
    if profile is None:
        profile = UserProfile(user_id=user.id, **payload)
        session.add(profile)
    else:
        for key, value in payload.items():
            setattr(profile, key, value)
        session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def acknowledge_disclosures(session: Session, user: User) -> User:
    user.disclosures_acknowledged_at = _now()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def issue_email_verification_token(session: Session, user: User) -> str:
    user.email_verification_token = token_urlsafe(24)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.email_verification_token or ""


def verify_email_token(session: Session, token: str) -> User:
    statement = select(User).where(User.email_verification_token == token)
    user = session.scalars(statement).first()
    if user is None:
        raise ValueError("Verification token is invalid")
    user.email_verified = True
    user.email_verification_token = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def issue_password_reset_token(session: Session, user: User) -> str:
    user.password_reset_token = token_urlsafe(24)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.password_reset_token or ""


def reset_password_with_token(session: Session, token: str, password: str) -> User:
    statement = select(User).where(User.password_reset_token == token)
    user = session.scalars(statement).first()
    if user is None:
        raise ValueError("Reset token is invalid")
    user.password_hash = hash_password(password)
    user.password_reset_token = None
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def change_password(session: Session, user: User, *, current_password: str, new_password: str) -> User:
    if not verify_password(current_password, user.password_hash):
        raise ValueError("Current password is invalid")
    user.password_hash = hash_password(new_password)
    user.password_reset_token = None
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@dataclass
class AuthResult:
    user: User | None
    error: str | None = None


def authenticate_user(session: Session, username: str, password: str, settings: Settings) -> AuthResult:
    user = get_user_by_username(session, username)
    if user is None or not user.is_active:
        return AuthResult(user=None, error="Invalid credentials")

    now = _now()
    locked_until = _coerce_utc(user.locked_until)
    if locked_until and locked_until > now:
        return AuthResult(user=None, error="Account temporarily locked. Try again later.")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_login_attempts:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_attempts = 0
        session.add(user)
        session.commit()
        locked_until = _coerce_utc(user.locked_until)
        if locked_until and locked_until > now:
            return AuthResult(user=None, error="Account temporarily locked. Try again later.")
        return AuthResult(user=None, error="Invalid credentials")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    sync_role_with_subscription(user)
    session.add(user)
    session.commit()
    session.refresh(user)
    return AuthResult(user=user)
