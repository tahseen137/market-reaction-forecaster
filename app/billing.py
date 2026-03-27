from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SubscriptionState, User
from app.user_service import get_subscription_state, sync_role_with_subscription

try:
    import stripe
except ImportError:  # pragma: no cover - exercised only when billing deps are absent
    stripe = None  # type: ignore[assignment]


def _now() -> datetime:
    return datetime.now(UTC)


def _configure_stripe(settings: Settings) -> None:
    if stripe is None:
        raise ValueError("Stripe dependency is not installed")
    stripe.api_key = settings.stripe_secret_key


def create_checkout_session(settings: Settings, user: User, *, billing_cycle: str, success_url: str, cancel_url: str) -> str:
    if not settings.billing_enabled or not settings.stripe_secret_key:
        raise ValueError("Billing is not configured")
    _configure_stripe(settings)
    price_id = settings.stripe_price_annual if billing_cycle == "annual" else settings.stripe_price_monthly
    if not price_id:
        raise ValueError("Stripe price is not configured")
    session = stripe.checkout.Session.create(
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=user.email,
        metadata={"user_id": user.id},
        line_items=[{"price": price_id, "quantity": 1}],
        subscription_data={"trial_period_days": settings.trial_days, "metadata": {"user_id": user.id}},
    )
    return str(session.url)


def create_portal_session(settings: Settings, subscription_state: SubscriptionState, *, return_url: str) -> str:
    if not settings.billing_enabled or not settings.stripe_secret_key:
        raise ValueError("Billing is not configured")
    if not subscription_state.stripe_customer_id:
        raise ValueError("Stripe customer is not available")
    _configure_stripe(settings)
    session = stripe.billing_portal.Session.create(customer=subscription_state.stripe_customer_id, return_url=return_url)
    return str(session.url)


def _upsert_subscription_from_payload(session: Session, user: User, payload: dict[str, Any]) -> SubscriptionState:
    subscription = get_subscription_state(user)
    subscription.stripe_customer_id = payload.get("customer") or subscription.stripe_customer_id
    subscription.stripe_subscription_id = payload.get("id") or subscription.stripe_subscription_id
    subscription.stripe_price_id = (
        payload.get("items", {}).get("data", [{}])[0].get("price", {}).get("id", subscription.stripe_price_id)
    )
    subscription.status = payload.get("status", subscription.status)
    current_period_end = payload.get("current_period_end")
    if current_period_end:
        subscription.current_period_end = datetime.fromtimestamp(int(current_period_end), tz=UTC)
    subscription.cancel_at_period_end = bool(payload.get("cancel_at_period_end", False))
    if subscription.stripe_price_id:
        subscription.plan_key = "pro_annual" if "annual" in subscription.stripe_price_id else "pro_monthly"
    sync_role_with_subscription(user)
    session.add_all([subscription, user])
    session.commit()
    session.refresh(subscription)
    return subscription


def handle_webhook_event(session: Session, settings: Settings, *, payload: bytes, signature: str | None) -> dict[str, str]:
    if not settings.stripe_secret_key:
        raise ValueError("Billing is not configured")
    _configure_stripe(settings)
    if settings.stripe_webhook_secret:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=settings.stripe_webhook_secret)
    else:
        event = stripe.Event.construct_from(json.loads(payload.decode("utf-8")), stripe.api_key)

    event_type = event["type"]
    data_object = event["data"]["object"]
    user_id = data_object.get("metadata", {}).get("user_id")
    if event_type == "checkout.session.completed":
        if user_id is None:
            return {"status": "ignored"}
        user = session.get(User, user_id)
        if user is None:
            return {"status": "ignored"}
        subscription = get_subscription_state(user)
        subscription.stripe_customer_id = data_object.get("customer")
        subscription.status = "active"
        subscription.plan_key = "pro_monthly"
        subscription.current_period_end = _now()
        sync_role_with_subscription(user)
        session.add_all([subscription, user])
        session.commit()
        return {"status": "processed"}
    if event_type in {"customer.subscription.updated", "customer.subscription.created"}:
        if user_id is None:
            return {"status": "ignored"}
        user = session.get(User, user_id)
        if user is None:
            return {"status": "ignored"}
        _upsert_subscription_from_payload(session, user, data_object)
        return {"status": "processed"}
    if event_type == "customer.subscription.deleted":
        if user_id is None:
            return {"status": "ignored"}
        user = session.get(User, user_id)
        if user is None:
            return {"status": "ignored"}
        subscription = get_subscription_state(user)
        subscription.status = "canceled"
        subscription.current_period_end = _now()
        sync_role_with_subscription(user)
        session.add_all([subscription, user])
        session.commit()
        return {"status": "processed"}
    return {"status": "ignored"}
