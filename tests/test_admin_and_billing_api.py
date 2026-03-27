from __future__ import annotations


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
