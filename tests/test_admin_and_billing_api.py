from __future__ import annotations

from tests.conftest import acknowledge, login, signup


def test_admin_user_management_and_manual_event(client, admin_headers):
    users = client.get("/api/admin/users")
    assert users.status_code == 200
    assert any(item["username"] == "admin" for item in users.json())

    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": "supportanalyst",
            "email": "supportanalyst@example.com",
            "full_name": "Support Analyst",
            "password": "support-password-123",
            "role": "subscriber",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    updated = client.patch(
        f"/api/admin/users/{user_id}",
        headers=admin_headers,
        json={"is_active": False, "role": "trial_user"},
    )
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False

    new_event = client.post(
        "/api/events",
        headers=admin_headers,
        json={
            "symbol": "NVDA",
            "event_type": "guidance",
            "headline": "NVIDIA raises near-term AI system guidance again",
            "summary": "Raised outlook supports another positive revision cycle.",
            "thesis": "Raised guidance reinforces datacenter demand momentum.",
            "directional_bias": 0.12,
            "source_label": "Manual Analyst Entry",
            "source_url": "https://example.com/nvda-guidance",
        },
    )
    assert new_event.status_code == 201

    events = client.get("/api/events")
    assert events.status_code == 200
    assert any(item["headline"] == "NVIDIA raises near-term AI system guidance again" for item in events.json())

    refresh = client.post("/api/admin/refresh-market", headers=admin_headers)
    assert refresh.status_code == 200


def test_billing_endpoints_require_configuration(client, admin_headers):
    checkout = client.post("/api/billing/create-checkout-session", headers=admin_headers, json={"billing_cycle": "monthly"})
    assert checkout.status_code == 503

    portal = client.post("/api/billing/create-portal-session", headers=admin_headers)
    assert portal.status_code == 503


def test_admin_validation_dashboard_and_exports(client):
    _, user_headers = signup(client, "validator")
    acknowledge(client, user_headers)

    recommendation = client.get("/recommendations/NVDA")
    assert recommendation.status_code == 200

    watchlist = client.post("/api/watchlists", headers=user_headers, json={"name": "Quality Basket", "symbols": ["NVDA", "AMD"]})
    assert watchlist.status_code == 201

    admin_headers = login(client)

    dashboard = client.get("/admin/validation")
    assert dashboard.status_code == 200
    assert "Validation dashboard" in dashboard.text

    summary = client.get("/api/admin/validation/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["funnel"]["counts"]["signup_completed"] >= 1
    assert payload["funnel"]["counts"]["recommendation_viewed"] >= 1
    assert payload["funnel"]["counts"]["watchlist_created"] >= 1
    assert "forecast_metrics" in payload
    assert "shadow_portfolio" in payload

    snapshots = client.get("/api/admin/validation/recommendation-snapshots.csv")
    assert snapshots.status_code == 200
    assert "snapshot_id,symbol" in snapshots.text

    reports = client.get("/api/admin/validation/reports.csv")
    assert reports.status_code == 200
    assert "report_date,generated_at" in reports.text

    activity = client.get("/api/activity", headers=admin_headers)
    assert activity.status_code == 200
    assert all(not item["action"].startswith("analytics.") for item in activity.json())
