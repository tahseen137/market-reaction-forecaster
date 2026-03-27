from __future__ import annotations

from tests.conftest import acknowledge, signup


def test_public_sample_feed_and_detail_gating(client):
    feed = client.get("/api/recommendations/feed")
    assert feed.status_code == 200
    payload = feed.json()
    assert payload
    assert all(item["delayed_sample"] is True for item in payload)

    detail = client.get("/api/recommendations/NVDA")
    assert detail.status_code == 401

    backtest = client.get("/api/backtests/summary")
    assert backtest.status_code == 200
    assert backtest.json()["sample_size"] > 0


def test_paid_watchlists_portfolio_and_reports(client):
    _, headers = signup(client, "dana")
    acknowledge(client, headers)

    watchlist = client.post("/api/watchlists", headers=headers, json={"name": "AI Basket", "symbols": ["NVDA", "AMD", "AAPL"]})
    assert watchlist.status_code == 201
    assert set(watchlist.json()["symbols"]) == {"NVDA", "AMD", "AAPL"}

    all_watchlists = client.get("/api/watchlists")
    assert all_watchlists.status_code == 200
    assert len(all_watchlists.json()) == 1

    portfolio = client.get("/api/model-portfolio")
    assert portfolio.status_code == 200
    assert portfolio.json()["open_positions"] >= 0

    rebuilt = client.post("/api/model-portfolio/rebuild", headers=headers)
    assert rebuilt.status_code == 200

    recommendation = client.get("/api/recommendations/NVDA")
    assert recommendation.status_code == 200
    assert recommendation.json()["action"] in {"buy", "hold", "sell"}

    report = client.get("/api/recommendations/NVDA/report.md")
    assert report.status_code == 200
    assert "# NVDA " in report.text

    backtest = client.get("/api/backtests/summary")
    backtest_id = backtest.json()["id"]
    backtest_detail = client.get(f"/api/backtests/{backtest_id}")
    assert backtest_detail.status_code == 200

    backtest_report = client.get(f"/api/backtests/{backtest_id}/report.md")
    assert backtest_report.status_code == 200
    assert "# Backtest Summary" in backtest_report.text
