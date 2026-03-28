from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import RecommendationOutcome
from app.reporting import build_backtest_markdown, build_recommendation_markdown
from app.schemas import BacktestRunRead, RecommendationDetailRead
from app.scoring import build_backtest_metrics, build_base_recommendation, personalize_recommendation
from app.services import default_profile_payload, get_recommendation_feed, refresh_validation_report


def test_scoring_outputs_actions_ranges_and_personalization():
    base = build_base_recommendation(
        symbol="NVDA",
        company_name="NVIDIA",
        event_type="earnings",
        headline="NVIDIA beats and raises AI guidance",
        summary="Strong hyperscaler demand keeps accelerating.",
        source_label="SEC EDGAR",
        directional_bias=0.12,
        day_change_pct=4.2,
        analog_count=8,
        source_status="real-time",
        benchmark_symbol="QQQ",
    )
    assert base.action == "buy"
    assert len(base.horizon_ranges) == 3

    personalized = personalize_recommendation(
        base,
        goal_primary="capital_preservation",
        risk_tolerance="conservative",
        max_drawdown_band="under_10",
        holding_period_preference="medium_term",
        sector_concentration_tolerance="low",
        experience_level="beginner",
    )
    assert personalized.action in {"hold", "sell", "buy"}
    assert personalized.profile_fit_score <= 0.95


def test_backtest_metrics_and_markdown_helpers():
    metrics = build_backtest_metrics(sample_size=40, buy_count=18, sell_count=6, avg_confidence=0.72)
    assert metrics.sample_size == 40
    assert metrics.hit_rate >= 0.49

    recommendation = RecommendationDetailRead.model_validate(
        {
            "symbol": "AMD",
            "company_name": "AMD",
            "action": "buy",
            "conviction_score": 4,
            "confidence_score": 0.74,
            "profile_fit_score": 0.71,
            "allocation_min_pct": 4.0,
            "allocation_max_pct": 8.0,
            "urgency_label": "high",
            "thesis_summary": "AMD screens as a buy.",
            "evidence_summary": "Hyperscaler accelerator design wins continue.",
            "invalidation_conditions": "Watch for a reversal in guidance.",
            "benchmark_symbol": "QQQ",
            "source_status": "real-time",
            "analog_sample_size": 6,
            "generated_at": "2026-03-26T12:00:00Z",
            "latest_event_id": "evt-1",
            "factor_scores": {"event_type_weight": 0.16},
            "horizon_ranges": [
                {"horizon_days": 1, "expected_return_low": -1.0, "expected_return_mid": 1.2, "expected_return_high": 2.4},
                {"horizon_days": 5, "expected_return_low": 0.4, "expected_return_mid": 3.8, "expected_return_high": 7.2},
                {"horizon_days": 20, "expected_return_low": 3.0, "expected_return_mid": 8.0, "expected_return_high": 15.0},
            ],
        }
    )
    markdown = build_recommendation_markdown(recommendation)
    assert "# AMD BUY" in markdown

    backtest = BacktestRunRead.model_validate(
        {
            "id": "bt-1",
            "scope_label": "Large-cap tech AI recommendation benchmark",
            "benchmark_symbol": "QQQ",
            "universe_version": "2026-03",
            "generated_at": "2026-03-26T12:00:00Z",
            "sample_size": 24,
            "hit_rate": 0.61,
            "win_rate": 0.59,
            "average_return": 6.2,
            "benchmark_return": 4.5,
            "max_drawdown": 8.4,
            "calibration_error": 0.08,
            "metadata_json": {"buy_count": 12},
        }
    )
    backtest_markdown = build_backtest_markdown(backtest)
    assert "# Backtest Summary" in backtest_markdown


def test_services_helpers_return_stable_defaults(session):
    defaults = default_profile_payload()
    assert defaults["risk_tolerance"] == "balanced"

    feed = get_recommendation_feed(session)
    symbols = [item["symbol"] for item in feed]
    assert symbols
    assert len(symbols) == len(set(symbols))


def test_validation_report_creates_and_resolves_outcomes(session, settings, monkeypatch):
    class StubQuoteClient:
        def __init__(self, runtime_settings):
            self.runtime_settings = runtime_settings

        def get_quote(self, symbol: str):
            now = datetime.now(UTC)
            if symbol == "QQQ":
                return type("Quote", (), {"symbol": symbol, "price": 500.0, "day_change_pct": 0.8, "as_of": now})()
            return type("Quote", (), {"symbol": symbol, "price": 250.0, "day_change_pct": 1.2, "as_of": now})()

    monkeypatch.setattr("app.services.TwelveDataClient", StubQuoteClient)

    first_report = refresh_validation_report(session, settings)
    assert first_report.funnel_json["counts"] == {}

    outcomes = session.query(RecommendationOutcome).all()  # type: ignore[attr-defined]
    assert outcomes

    due_outcome = outcomes[0]
    due_outcome.reference_price = 200.0
    due_outcome.benchmark_reference_price = 400.0
    due_outcome.target_at = datetime.now(UTC) - timedelta(days=1)
    session.add(due_outcome)
    session.commit()

    refreshed_report = refresh_validation_report(session, settings)
    session.refresh(due_outcome)

    assert due_outcome.status == "resolved"
    assert due_outcome.observed_return_pct == 25.0
    assert refreshed_report.forecast_metrics_json["resolved_outcomes"] >= 1
    assert "average_excess_return_pct" in refreshed_report.shadow_portfolio_json
