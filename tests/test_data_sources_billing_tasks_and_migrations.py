from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from types import SimpleNamespace

import app.billing as billing_module
from app.billing import create_checkout_session, create_portal_session, handle_webhook_event
from app.data_sources import FinnhubClient, SecEdgarClient, TwelveDataClient
from app.tasks import refresh_market_state_task
from app.user_service import create_user, get_subscription_state


def test_data_source_fallbacks_without_live_keys(settings):
    quote = TwelveDataClient(settings).get_quote("NVDA")
    assert quote.symbol == "NVDA"
    assert quote.source_status == "delayed"

    assert FinnhubClient(settings).get_company_news("NVDA") == []
    assert SecEdgarClient(settings).get_recent_filings("NVDA", None) == []


def test_billing_errors_without_configuration(session, settings):
    user = create_user(
        session,
        username="billinguser",
        email="billinguser@example.com",
        password="billing-password-123",
        full_name="Billing User",
        settings=settings,
    )

    try:
        create_checkout_session(settings, user, billing_cycle="monthly", success_url="https://example.com/s", cancel_url="https://example.com/c")
    except ValueError as exc:
        assert "Billing is not configured" in str(exc)
    else:
        raise AssertionError("checkout should fail without billing config")

    try:
        handle_webhook_event(session, settings, payload=b"{}", signature=None)
    except ValueError as exc:
        assert "Billing is not configured" in str(exc)
    else:
        raise AssertionError("webhook should fail without billing config")


def test_billing_happy_path_with_stubbed_stripe(session, settings, monkeypatch):
    user = create_user(
        session,
        username="stripeuser",
        email="stripeuser@example.com",
        password="stripe-password-123",
        full_name="Stripe User",
        settings=settings,
    )
    configured = settings.model_copy(
        update={
            "stripe_secret_key": "sk_test",
            "stripe_publishable_key": "pk_test",
            "stripe_price_monthly": "price_monthly",
            "stripe_price_annual": "price_annual",
        }
    )

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(Session=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(url="https://checkout.test"))),
        billing_portal=SimpleNamespace(Session=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(url="https://portal.test"))),
        Event=SimpleNamespace(construct_from=lambda payload, api_key: payload),
        Webhook=SimpleNamespace(construct_event=lambda payload, sig_header, secret: {"type": "noop", "data": {"object": {}}}),
    )
    monkeypatch.setattr(billing_module, "stripe", fake_stripe)

    checkout_url = create_checkout_session(
        configured,
        user,
        billing_cycle="annual",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel",
    )
    assert checkout_url == "https://checkout.test"

    subscription = get_subscription_state(user)
    subscription.stripe_customer_id = "cus_123"
    session.add(subscription)
    session.commit()

    portal_url = create_portal_session(configured, subscription, return_url="https://example.com/account")
    assert portal_url == "https://portal.test"

    checkout_event = {
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"user_id": user.id}, "customer": "cus_999"}},
    }
    assert handle_webhook_event(session, configured, payload=json.dumps(checkout_event).encode("utf-8"), signature=None)["status"] == "processed"

    subscription_event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "metadata": {"user_id": user.id},
                "customer": "cus_999",
                "id": "sub_123",
                "status": "active",
                "items": {"data": [{"price": {"id": "price_annual"}}]},
                "current_period_end": 1770000000,
                "cancel_at_period_end": False,
            }
        },
    }
    assert handle_webhook_event(session, configured, payload=json.dumps(subscription_event).encode("utf-8"), signature=None)["status"] == "processed"

    deleted_event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"user_id": user.id}}},
    }
    assert handle_webhook_event(session, configured, payload=json.dumps(deleted_event).encode("utf-8"), signature=None)["status"] == "processed"


def test_task_entrypoint_runs_with_eager_settings(monkeypatch, settings):
    called = {"count": 0}

    def fake_refresh_market_state(db_session, runtime_settings):
        called["count"] += 1
        assert runtime_settings.app_env == "test"

    monkeypatch.setattr("app.tasks.get_settings", lambda: settings)
    monkeypatch.setattr("app.tasks.refresh_market_state", fake_refresh_market_state)
    refresh_market_state_task()
    assert called["count"] == 1


def test_alembic_upgrade_head_creates_market_tables(tmp_path: Path):
    database_path = tmp_path / "migration.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")

    import sqlite3

    with sqlite3.connect(database_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "events", "recommendation_snapshots", "user_recommendations", "backtest_runs"}.issubset(tables)
