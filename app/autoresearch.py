from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.models import RecommendationOutcome, RecommendationSnapshot
from app.scoring import EVENT_TYPE_WEIGHTS


WEIGHT_PROFILE_NAME = "cassandra-autoresearch-v1"
BASELINE_WEIGHT_OVERRIDES: dict[str, float] = {
    "mirofish_weight": 0.16,
    "chaos_penalty_weight": 0.22,
    "analog_density_weight": 0.01,
    **{f"event_type::{event_type}": weight for event_type, weight in EVENT_TYPE_WEIGHTS.items()},
}


def _now() -> datetime:
    return datetime.now(UTC)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _artifact_path(settings: Settings) -> Path:
    return settings.uploads_dir / "cassandra" / "autoresearch-latest.json"


def _snapshot_query():
    return select(RecommendationSnapshot).options(
        selectinload(RecommendationSnapshot.latest_event),
        selectinload(RecommendationSnapshot.security),
    )


def _outcome_query():
    return select(RecommendationOutcome).options(
        selectinload(RecommendationOutcome.recommendation_snapshot).selectinload(RecommendationSnapshot.latest_event),
        selectinload(RecommendationOutcome.recommendation_snapshot).selectinload(RecommendationSnapshot.security),
    )


def load_autoresearch_artifact(settings: Settings) -> dict[str, Any] | None:
    path = _artifact_path(settings)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_weight_overrides(settings: Settings) -> tuple[dict[str, float], str]:
    artifact = load_autoresearch_artifact(settings)
    if not artifact:
        return dict(BASELINE_WEIGHT_OVERRIDES), "baseline"
    updated = artifact.get("updated_weights") or {}
    overrides = {key: float(value) for key, value in updated.items() if isinstance(value, (int, float))}
    return (dict(BASELINE_WEIGHT_OVERRIDES) | overrides, str(artifact.get("weight_profile_name", WEIGHT_PROFILE_NAME)))


def _retune(base_weight: float, alignment: float, *, min_factor: float, max_factor: float) -> float:
    factor = 1 + alignment * 0.35
    factor = _clamp(factor, min_factor, max_factor)
    return round(base_weight * factor, 4)


def _serialize_example(outcome: RecommendationOutcome) -> dict[str, Any]:
    snapshot = outcome.recommendation_snapshot
    event_type = snapshot.latest_event.event_type if snapshot and snapshot.latest_event else "macro"
    return {
        "symbol": snapshot.security.symbol if snapshot and snapshot.security else None,
        "event_type": event_type,
        "action": outcome.action,
        "horizon_days": outcome.horizon_days,
        "strategy_return_pct": outcome.strategy_return_pct,
        "benchmark_return_pct": outcome.benchmark_return_pct,
        "excess_return_pct": outcome.excess_return_pct,
        "directional_correct": outcome.directional_correct,
        "mirofish_sentiment": snapshot.factor_scores.get("mirofish_sentiment", 0.0) if snapshot else 0.0,
        "chaos_score": snapshot.factor_scores.get("chaos_score", 0.0) if snapshot else 0.0,
    }


def _bootstrap_from_snapshots(snapshots: list[RecommendationSnapshot]) -> tuple[dict[str, float], list[str], dict[str, Any]]:
    updated = dict(BASELINE_WEIGHT_OVERRIDES)
    avg_chaos = _avg([float(snapshot.factor_scores.get("chaos_score", 0.0)) for snapshot in snapshots])
    avg_consensus = _avg([float(snapshot.factor_scores.get("mirofish_consensus", 0.0)) for snapshot in snapshots])
    avg_sentiment = _avg([abs(float(snapshot.factor_scores.get("mirofish_sentiment", 0.0))) for snapshot in snapshots])
    recommendations: list[str] = []

    if avg_consensus >= 0.58 and avg_sentiment >= 0.12:
        updated["mirofish_weight"] = round(updated["mirofish_weight"] * 1.08, 4)
        recommendations.append("Bootstrap boost: raise MiroFish weight 8% because the current snapshot set shows consistent persona alignment.")
    else:
        recommendations.append("Bootstrap hold: keep MiroFish weight near baseline until more resolved outcomes accumulate.")

    if avg_chaos >= 0.45:
        updated["chaos_penalty_weight"] = round(updated["chaos_penalty_weight"] * 1.1, 4)
        recommendations.append("Bootstrap hardening: increase chaos penalty 10% because recent snapshots are noisy and horizon stability is short.")
    else:
        recommendations.append("Bootstrap hold: chaos penalty stays near baseline because current snapshot instability is moderate.")

    scorecard = {
        "avg_snapshot_chaos": avg_chaos,
        "avg_snapshot_consensus": avg_consensus,
        "avg_abs_mirofish_sentiment": avg_sentiment,
    }
    return updated, recommendations, scorecard


def run_autoresearch_loop(session: Session, settings: Settings) -> dict[str, Any]:
    path = _artifact_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)

    resolved_outcomes = [
        outcome
        for outcome in session.scalars(_outcome_query().order_by(RecommendationOutcome.created_at.desc()))
        if outcome.status == "resolved" and outcome.strategy_return_pct is not None and outcome.recommendation_snapshot is not None
    ]
    snapshots = list(session.scalars(_snapshot_query().order_by(RecommendationSnapshot.generated_at.desc())))

    updated_weights = dict(BASELINE_WEIGHT_OVERRIDES)
    recommendations: list[str] = []
    exemplar_cases: list[dict[str, Any]] = []
    scorecard: dict[str, Any] = {}
    mode = "bootstrap"

    if resolved_outcomes:
        mode = "resolved_outcomes"
        event_alignments: dict[str, list[float]] = {event_type: [] for event_type in EVENT_TYPE_WEIGHTS}
        mirofish_alignment: list[float] = []
        chaos_pressure: list[float] = []
        excess_returns: list[float] = []
        by_horizon: dict[str, list[float]] = {}

        sorted_examples = sorted(resolved_outcomes, key=lambda outcome: abs(float(outcome.excess_return_pct or 0.0)), reverse=True)
        exemplar_cases = [_serialize_example(item) for item in sorted_examples[:5]]

        for outcome in resolved_outcomes:
            snapshot = outcome.recommendation_snapshot
            event_type = snapshot.latest_event.event_type if snapshot.latest_event else "macro"
            excess = float(outcome.excess_return_pct or 0.0)
            excess_returns.append(excess)
            quality = _clamp(excess / 6, -1.0, 1.0)
            if outcome.directional_correct:
                quality = _clamp(quality + 0.2, -1.0, 1.0)
            else:
                quality = _clamp(quality - 0.2, -1.0, 1.0)
            event_alignments.setdefault(event_type, []).append(quality)
            by_horizon.setdefault(str(outcome.horizon_days), []).append(quality)

            mirofish_sentiment = float(snapshot.factor_scores.get("mirofish_sentiment", 0.0))
            mirofish_alignment.append(_clamp((1 if mirofish_sentiment * quality >= 0 else -1) * abs(mirofish_sentiment) * abs(quality), -1.0, 1.0))

            chaos_score = float(snapshot.factor_scores.get("chaos_score", 0.0))
            chaos_pressure.append(_clamp(chaos_score * (-quality), -1.0, 1.0))

        updated_weights["mirofish_weight"] = _retune(
            BASELINE_WEIGHT_OVERRIDES["mirofish_weight"],
            _avg(mirofish_alignment),
            min_factor=0.75,
            max_factor=1.35,
        )
        updated_weights["chaos_penalty_weight"] = _retune(
            BASELINE_WEIGHT_OVERRIDES["chaos_penalty_weight"],
            _avg(chaos_pressure),
            min_factor=0.75,
            max_factor=1.45,
        )

        for event_type, alignments in event_alignments.items():
            if not alignments:
                continue
            key = f"event_type::{event_type}"
            updated_weights[key] = _retune(
                BASELINE_WEIGHT_OVERRIDES[key],
                _avg(alignments),
                min_factor=0.7,
                max_factor=1.3,
            )

        mirofish_delta = updated_weights["mirofish_weight"] - BASELINE_WEIGHT_OVERRIDES["mirofish_weight"]
        chaos_delta = updated_weights["chaos_penalty_weight"] - BASELINE_WEIGHT_OVERRIDES["chaos_penalty_weight"]
        recommendations.append(
            f"MiroFish weight {'raised' if mirofish_delta >= 0 else 'trimmed'} to {updated_weights['mirofish_weight']:.4f} based on realized alignment across {len(resolved_outcomes)} resolved outcomes."
        )
        recommendations.append(
            f"Chaos penalty {'raised' if chaos_delta >= 0 else 'trimmed'} to {updated_weights['chaos_penalty_weight']:.4f} using realized excess-return damage from unstable setups."
        )
        strongest_events = sorted(
            ((event_type, _avg(values)) for event_type, values in event_alignments.items() if values),
            key=lambda item: item[1],
            reverse=True,
        )
        if strongest_events:
            best_event, best_alignment = strongest_events[0]
            recommendations.append(
                f"Best recent event family: {best_event} ({best_alignment:+.2f} alignment). Preserve or slightly favor that catalyst weight in the next rebuild cycle."
            )
        weakest_events = [item for item in strongest_events if item[1] < 0]
        if weakest_events:
            weak_event, weak_alignment = weakest_events[-1]
            recommendations.append(
                f"Weakest recent event family: {weak_event} ({weak_alignment:+.2f} alignment). Treat those setups with extra caution until more data lands."
            )

        scorecard = {
            "average_excess_return_pct": _avg(excess_returns),
            "resolved_outcomes": len(resolved_outcomes),
            "by_horizon_quality": {horizon: _avg(values) for horizon, values in by_horizon.items()},
            "mirofish_alignment": _avg(mirofish_alignment),
            "chaos_pressure": _avg(chaos_pressure),
        }
    else:
        updated_weights, recommendations, scorecard = _bootstrap_from_snapshots(snapshots)

    artifact = {
        "generated_at": _now().isoformat(),
        "weight_profile_name": WEIGHT_PROFILE_NAME,
        "mode": mode,
        "observations": {
            "snapshot_count": len(snapshots),
            "resolved_outcomes": len(resolved_outcomes),
        },
        "baseline_weights": BASELINE_WEIGHT_OVERRIDES,
        "updated_weights": updated_weights,
        "weight_deltas": {
            key: round(updated_weights.get(key, 0.0) - BASELINE_WEIGHT_OVERRIDES.get(key, 0.0), 4)
            for key in BASELINE_WEIGHT_OVERRIDES
        },
        "scorecard": scorecard,
        "recommendations": recommendations,
        "exemplar_cases": exemplar_cases,
        "artifact_path": str(path),
    }
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return artifact
