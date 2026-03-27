from __future__ import annotations


def test_public_pages_render(client):
    for path, text in [
        ("/", "AI-powered buy, hold, and sell calls"),
        ("/pricing", "One product. One universe."),
        ("/legal", "Research, not guaranteed outcomes."),
        ("/login", "Log in to your account"),
        ("/signup", "Create your account"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text


def test_dashboard_redirects_for_anonymous_users(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert "/login" in response.headers["location"]


def test_authenticated_pages_render(client, admin_headers):
    for path, text in [
        ("/dashboard", "Recommendation dashboard"),
        ("/watchlists", "Watchlists"),
        ("/events", "Event library"),
        ("/backtests", "Large-cap tech AI recommendation benchmark"),
        ("/paper-portfolio", "Model portfolio"),
        ("/account", "Profile, billing, and system"),
        ("/admin/users", "Users"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text


def test_account_activity_is_scoped_to_current_user(client, admin_headers):
    signup_response = client.post(
        "/api/session/signup",
        json={
            "username": "erin",
            "email": "erin@example.com",
            "full_name": "Erin User",
            "password": "test-password-123",
        },
    )
    assert signup_response.status_code == 201

    account_page = client.get("/account")
    assert account_page.status_code == 200
    assert "erin created an account" in account_page.text
    assert "admin logged in" not in account_page.text
