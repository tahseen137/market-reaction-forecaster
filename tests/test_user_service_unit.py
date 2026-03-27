from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.user_service import (
    authenticate_user,
    can_manage_users,
    count_users,
    create_user,
    get_subscription_state,
    get_user_by_email,
    get_user_by_username,
    has_paid_access,
    issue_email_verification_token,
    issue_password_reset_token,
    list_users,
    reset_password_with_token,
    update_user,
    verify_email_token,
)


def test_user_lookup_tokens_and_updates(session, settings):
    user = create_user(
        session,
        username="lookupuser",
        email="lookupuser@example.com",
        password="lookup-password-123",
        full_name="Lookup User",
        settings=settings,
    )

    assert count_users(session) >= 2
    assert get_user_by_username(session, "LookupUser").id == user.id
    assert get_user_by_email(session, "LOOKUPUSER@example.com").id == user.id
    assert any(item.id == user.id for item in list_users(session))
    assert can_manage_users(user) is False

    verify_token = issue_email_verification_token(session, user)
    verified = verify_email_token(session, verify_token)
    assert verified.email_verified is True

    reset_token = issue_password_reset_token(session, user)
    reset = reset_password_with_token(session, reset_token, "new-lookup-password-123")
    assert reset.password_reset_token is None

    updated = update_user(session, user, full_name="Lookup User Updated", role="subscriber", is_active=False)
    assert updated.full_name == "Lookup User Updated"
    assert updated.role == "subscriber"
    assert updated.is_active is False


def test_user_authentication_lockout_and_paid_access(session, settings):
    user = create_user(
        session,
        username="authuser",
        email="authuser@example.com",
        password="auth-password-123",
        full_name="Auth User",
        settings=settings,
    )

    for _ in range(settings.max_login_attempts):
        result = authenticate_user(session, "authuser", "wrong-password", settings)
    assert result.user is None
    assert "locked" in result.error.lower()

    locked = authenticate_user(session, "authuser", "auth-password-123", settings)
    assert locked.user is None

    user.locked_until = datetime.now(UTC) - timedelta(minutes=1)
    subscription = get_subscription_state(user)
    subscription.status = "active"
    session.add_all([user, subscription])
    session.commit()

    success = authenticate_user(session, "authuser", "auth-password-123", settings)
    assert success.user is not None
    assert has_paid_access(success.user) is True

    subscription.status = "trialing"
    subscription.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    session.add(subscription)
    session.commit()
    session.refresh(user)
    assert has_paid_access(user) is False
