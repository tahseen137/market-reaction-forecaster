from __future__ import annotations

from tests.conftest import acknowledge, login, signup


def test_signup_session_and_disclosure_gating(client):
    payload, headers = signup(client, "alice")

    assert payload["authenticated"] is True
    assert payload["current_user"]["username"] == "alice"
    assert payload["subscription"]["status"] == "trialing"

    gated = client.get("/api/recommendations/feed")
    assert gated.status_code == 409

    acknowledged = acknowledge(client, headers)
    assert acknowledged["current_user"]["disclosures_acknowledged_at"] is not None

    feed = client.get("/api/recommendations/feed")
    assert feed.status_code == 200
    assert any(item["delayed_sample"] is False for item in feed.json())


def test_forgot_and_reset_password_flow(client):
    payload, headers = signup(client, "charlie")
    assert payload["authenticated"] is True

    forgot = client.post("/api/session/forgot-password", json={"email": "charlie@example.com"})
    assert forgot.status_code == 200
    token = forgot.json()["debug_token"]
    assert token

    reset = client.post("/api/session/reset-password", json={"token": token, "password": "new-password-456"})
    assert reset.status_code == 200

    logout = client.post("/api/session/logout", headers=headers)
    assert logout.status_code == 204

    relogin = client.post("/api/session/login", json={"username": "charlie", "password": "new-password-456", "next_path": "/dashboard"})
    assert relogin.status_code == 200


def test_profile_session_and_subscription_endpoints(client, admin_headers):
    session_status = client.get("/api/session")
    assert session_status.status_code == 200
    assert session_status.json()["authenticated"] is True

    profile_update = client.post(
        "/api/profile",
        headers=admin_headers,
        json={
            "age_band": "35_44",
            "investable_amount_band": "250k_1m",
            "goal_primary": "aggressive_growth",
            "risk_tolerance": "aggressive",
            "max_drawdown_band": "under_20",
            "holding_period_preference": "swing",
            "income_stability_band": "stable",
            "sector_concentration_tolerance": "high",
            "experience_level": "advanced",
        },
    )
    assert profile_update.status_code == 200
    assert profile_update.json()["risk_tolerance"] == "aggressive"

    profile = client.get("/api/profile")
    assert profile.status_code == 200
    assert profile.json()["experience_level"] == "advanced"

    subscription = client.get("/api/account/subscription")
    assert subscription.status_code == 200
    assert subscription.json()["status"] in {"active", "trialing"}

    system_status = client.get("/api/system/status")
    assert system_status.status_code == 200
    assert system_status.json()["scheduler_enabled"] is True
    assert any(item["connector_name"] == "market_refresh" for item in system_status.json()["connectors"])

    changed = client.post(
        "/api/account/change-password",
        headers=admin_headers,
        json={"current_password": "pilot-password", "new_password": "pilot-password-2"},
    )
    assert changed.status_code == 200

    logout = client.post("/api/session/logout", headers=admin_headers)
    assert logout.status_code == 204
    protected = client.get("/api/profile")
    assert protected.status_code == 401

    relogin = client.post("/api/session/login", json={"username": "admin", "password": "pilot-password-2", "next_path": "/dashboard"})
    assert relogin.status_code == 200
