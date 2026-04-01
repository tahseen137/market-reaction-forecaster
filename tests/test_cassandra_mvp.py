from __future__ import annotations

from sqlalchemy import select

from app.autoresearch import BASELINE_WEIGHT_OVERRIDES, run_autoresearch_loop
from app.models import RecommendationOutcome, RecommendationSnapshot, Security
from app.scoring import build_base_recommendation
from app.services import archive_validation_run, load_validation_run_artifact, refresh_validation_report, seed_demo_content
from tests.conftest import acknowledge, login, signup


def test_cassandra_scoring_builds_persona_and_chaos_artifacts():
    recommendation = build_base_recommendation(
        symbol="NVDA",
        company_name="NVIDIA",
        event_type="earnings",
        headline="NVIDIA beats estimates and raises AI guidance",
        summary="Strong demand accelerated and the company expanded datacenter capacity.",
        source_label="Investor Relations",
        directional_bias=0.18,
        day_change_pct=4.8,
        analog_count=6,
        source_status="delayed",
        benchmark_symbol="QQQ",
    )

    assert recommendation.analysis_artifacts["mirofish"]["regime"] in {"bullish", "bearish", "cross-current"}
    assert len(recommendation.analysis_artifacts["mirofish"]["personas"]) == 4
    assert recommendation.analysis_artifacts["chaos"]["predictability_horizon_days"] >= 1
    assert "mirofish_sentiment" in recommendation.factor_scores
    assert recommendation.action in {"buy", "hold", "sell"}


def test_autoresearch_runs_with_resolved_outcomes(session, settings):
    refresh_validation_report(session, settings)
    outcome = session.scalars(select(RecommendationOutcome)).first()
    assert outcome is not None

    outcome.status = "resolved"
    outcome.strategy_return_pct = 5.4
    outcome.benchmark_return_pct = 1.2
    outcome.excess_return_pct = 4.2
    outcome.directional_correct = True
    session.add(outcome)
    session.commit()

    artifact = run_autoresearch_loop(session, settings)
    assert artifact["mode"] == "resolved_outcomes"
    assert artifact["observations"]["resolved_outcomes"] >= 1
    assert artifact["updated_weights"]["mirofish_weight"] != BASELINE_WEIGHT_OVERRIDES["mirofish_weight"]


def test_validation_run_archives_live_shadow_artifacts(session, settings):
    artifact = archive_validation_run(session, settings, reason="pytest", top_calls=4)

    assert artifact["reason"] == "pytest"
    assert artifact["run_id"]
    assert artifact["tracking_note"]
    assert len(artifact["top_live_calls"]) == 4
    assert artifact["forecast_metrics"]["open_outcomes"] >= 1

    json_path = settings.uploads_dir / "cassandra" / "validation-runs" / f"{artifact['run_id']}.json"
    csv_path = settings.uploads_dir / "cassandra" / "validation-runs" / f"{artifact['run_id']}-calls.csv"
    latest_path = settings.uploads_dir / "cassandra" / "validation-runs" / "latest.json"

    assert json_path.exists()
    assert csv_path.exists()
    assert latest_path.exists()
    assert "horizon_1_status" in csv_path.read_text()

    latest_artifact = load_validation_run_artifact(settings)
    assert latest_artifact is not None
    assert latest_artifact["run_id"] == artifact["run_id"]
    assert latest_artifact["top_live_calls"][0]["horizons"]["1"]["runtime_status"] in {"pending", "due", "resolved"}


def test_seed_demo_content_backfills_legacy_snapshots(session, settings):
    legacy_snapshot = session.scalars(
        select(RecommendationSnapshot)
        .join(RecommendationSnapshot.security)
        .where(Security.symbol == "NVDA")
        .order_by(RecommendationSnapshot.generated_at.desc())
    ).first()
    assert legacy_snapshot is not None

    legacy_snapshot.analysis_artifacts = {}
    session.add(legacy_snapshot)
    session.commit()
    legacy_id = legacy_snapshot.id

    seed_demo_content(session, settings)

    refreshed_snapshot = session.scalars(
        select(RecommendationSnapshot)
        .join(RecommendationSnapshot.security)
        .where(Security.symbol == "NVDA")
        .order_by(RecommendationSnapshot.generated_at.desc())
    ).first()
    assert refreshed_snapshot is not None
    assert refreshed_snapshot.id != legacy_id
    assert refreshed_snapshot.analysis_artifacts["mirofish"]["regime"] in {"bullish", "bearish", "cross-current"}
    assert refreshed_snapshot.analysis_artifacts["chaos"]["predictability_horizon_days"] >= 1


def test_recommendation_api_exposes_cassandra_artifacts_and_validation_runner(client):
    _, headers = signup(client, "cass")
    acknowledge(client, headers)

    recommendation = client.get("/api/recommendations/NVDA")
    assert recommendation.status_code == 200
    payload = recommendation.json()
    assert payload["mirofish_analysis"]["regime"] in {"bullish", "bearish", "cross-current"}
    assert len(payload["mirofish_analysis"]["personas"]) == 4
    assert payload["chaos_analysis"]["predictability_horizon_days"] >= 1
    assert payload["weight_profile_name"]

    report = client.get("/api/recommendations/NVDA/report.md")
    assert report.status_code == 200
    assert "## MiroFish Sentiment Simulation" in report.text
    assert "## Predictability Horizon" in report.text

    admin_headers = login(client)

    summary = client.get("/api/admin/validation/summary")
    assert summary.status_code == 200
    assert summary.json()["autoresearch"]["weight_profile_name"] == "cassandra-autoresearch-v1"
    assert summary.json()["live_validation_runs"]["recent"] == []

    validation_run = client.post("/api/admin/cassandra/validation/run", headers=admin_headers)
    assert validation_run.status_code == 200
    validation_payload = validation_run.json()
    assert validation_payload["run_id"]
    assert len(validation_payload["top_live_calls"]) == 5

    validation_runs = client.get("/api/admin/cassandra/validation/runs")
    assert validation_runs.status_code == 200
    runs_payload = validation_runs.json()
    assert runs_payload[0]["run_id"] == validation_payload["run_id"]

    validation_detail = client.get(f"/api/admin/cassandra/validation/runs/{validation_payload['run_id']}")
    assert validation_detail.status_code == 200
    assert validation_detail.json()["artifact_paths"]["csv"].endswith("-calls.csv")

    refreshed_summary = client.get("/api/admin/validation/summary")
    assert refreshed_summary.status_code == 200
    assert refreshed_summary.json()["live_validation_runs"]["latest"]["run_id"] == validation_payload["run_id"]

    rerun = client.post("/api/admin/cassandra/autoresearch/run", headers=admin_headers)
    assert rerun.status_code == 200
    assert rerun.json()["weight_profile_name"] == "cassandra-autoresearch-v1"

    artifact = client.get("/api/admin/cassandra/autoresearch")
    assert artifact.status_code == 200
    assert artifact.json()["observations"]["snapshot_count"] >= 1

    artifact_path = client.app.state.settings.uploads_dir / "cassandra" / "autoresearch-latest.json"
    validation_json_path = client.app.state.settings.uploads_dir / "cassandra" / "validation-runs" / f"{validation_payload['run_id']}.json"
    assert artifact_path.exists()
    assert validation_json_path.exists()
