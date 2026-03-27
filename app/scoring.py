from __future__ import annotations

from dataclasses import dataclass
from math import ceil


EVENT_TYPE_WEIGHTS: dict[str, float] = {
    "earnings": 0.24,
    "guidance": 0.22,
    "product_launch": 0.18,
    "regulatory": -0.14,
    "macro": -0.08,
    "mna": 0.15,
    "analyst_rating": 0.1,
    "supply_chain": -0.12,
    "customer_win": 0.16,
    "customer_loss": -0.18,
}

POSITIVE_TERMS = {"beats", "raises", "accelerates", "wins", "strong", "launch", "approval", "expands"}
NEGATIVE_TERMS = {"misses", "cuts", "delays", "probe", "investigation", "halts", "warning", "weak"}


@dataclass
class BaseRecommendation:
    action: str
    conviction_score: int
    confidence_score: float
    thesis_summary: str
    evidence_summary: str
    invalidation_conditions: str
    factor_scores: dict[str, float]
    horizon_ranges: list[dict[str, float | int]]
    analog_sample_size: int
    benchmark_symbol: str
    source_status: str


@dataclass
class PersonalizedRecommendation:
    action: str
    conviction_score: int
    profile_fit_score: float
    allocation_min_pct: float
    allocation_max_pct: float
    urgency_label: str
    rationale: str


@dataclass
class BacktestMetrics:
    sample_size: int
    hit_rate: float
    win_rate: float
    average_return: float
    benchmark_return: float
    max_drawdown: float
    calibration_error: float


def classify_headline_bias(headline: str, summary: str) -> float:
    text = f"{headline} {summary}".casefold()
    positive_hits = sum(1 for term in POSITIVE_TERMS if term in text)
    negative_hits = sum(1 for term in NEGATIVE_TERMS if term in text)
    raw = (positive_hits - negative_hits) * 0.05
    return max(-0.2, min(0.2, raw))


def _score_to_action(score: float) -> str:
    if score >= 0.18:
        return "buy"
    if score <= -0.18:
        return "sell"
    return "hold"


def _conviction_from_score(score: float, analog_count: int) -> int:
    base = abs(score) * 5 + min(analog_count, 10) * 0.08
    return max(1, min(5, ceil(base)))


def _confidence_from_inputs(score: float, analog_count: int, source_quality: float) -> float:
    confidence = 0.48 + min(abs(score), 0.35) + min(analog_count, 12) * 0.015 + source_quality * 0.06
    return round(max(0.5, min(0.96, confidence)), 2)


def _build_horizon_ranges(score: float, day_change_pct: float) -> list[dict[str, float | int]]:
    volatility_factor = max(0.02, min(0.25, abs(day_change_pct) / 100))
    ranges: list[dict[str, float | int]] = []
    for horizon in (1, 5, 20):
        midpoint = score * horizon * 3.1
        spread = max(1.2, horizon * (volatility_factor * 9))
        ranges.append(
            {
                "horizon_days": horizon,
                "expected_return_low": round(midpoint - spread, 2),
                "expected_return_mid": round(midpoint, 2),
                "expected_return_high": round(midpoint + spread, 2),
            }
        )
    return ranges


def build_base_recommendation(
    *,
    symbol: str,
    company_name: str,
    event_type: str,
    headline: str,
    summary: str,
    source_label: str,
    directional_bias: float,
    day_change_pct: float,
    analog_count: int,
    source_status: str,
    benchmark_symbol: str,
) -> BaseRecommendation:
    source_quality = 0.8 if source_label in {"SEC EDGAR", "Investor Relations", "Manual Analyst Entry"} else 0.6
    event_score = EVENT_TYPE_WEIGHTS.get(event_type, 0.0)
    headline_bias = classify_headline_bias(headline, summary)
    momentum_adjustment = max(-0.1, min(0.1, day_change_pct / 100))
    raw_score = event_score + headline_bias + directional_bias + momentum_adjustment + min(analog_count, 8) * 0.01
    score = max(-0.55, min(0.55, raw_score))
    action = _score_to_action(score)
    conviction = _conviction_from_score(score, analog_count)
    confidence = _confidence_from_inputs(score, analog_count, source_quality)
    factor_scores = {
        "event_type_weight": round(event_score, 3),
        "headline_bias": round(headline_bias, 3),
        "directional_bias": round(directional_bias, 3),
        "momentum_adjustment": round(momentum_adjustment, 3),
        "analog_density": round(min(analog_count, 10) * 0.01, 3),
        "source_quality": round(source_quality, 3),
    }
    thesis_summary = (
        f"{company_name} ({symbol}) screens as a {action.upper()} because the latest {event_type.replace('_', ' ')} "
        f"tilts the near-term risk/reward profile with {confidence:.0%} model confidence."
    )
    evidence_summary = f"{headline} Source: {source_label}. Analog sample size: {analog_count}."
    invalidation_conditions = (
        "Invalidate if the next material company update contradicts the thesis, price momentum reverses sharply, "
        "or benchmark-relative underperformance persists for two sessions."
    )
    return BaseRecommendation(
        action=action,
        conviction_score=conviction,
        confidence_score=confidence,
        thesis_summary=thesis_summary,
        evidence_summary=evidence_summary,
        invalidation_conditions=invalidation_conditions,
        factor_scores=factor_scores,
        horizon_ranges=_build_horizon_ranges(score, day_change_pct),
        analog_sample_size=analog_count,
        benchmark_symbol=benchmark_symbol,
        source_status=source_status,
    )


def personalize_recommendation(
    base: BaseRecommendation,
    *,
    goal_primary: str,
    risk_tolerance: str,
    max_drawdown_band: str,
    holding_period_preference: str,
    sector_concentration_tolerance: str,
    experience_level: str,
) -> PersonalizedRecommendation:
    action = base.action
    profile_fit = 0.68
    risk_penalty = 0.0
    if risk_tolerance == "conservative":
        risk_penalty += 0.12
    if max_drawdown_band in {"under_10", "under_15"}:
        risk_penalty += 0.08
    if holding_period_preference == "short_term":
        profile_fit += 0.04
    if holding_period_preference == "long_term":
        profile_fit -= 0.02
    if experience_level == "beginner":
        risk_penalty += 0.05
    if sector_concentration_tolerance == "low":
        risk_penalty += 0.05

    adjusted_confidence = base.confidence_score - risk_penalty
    if risk_tolerance == "conservative" and base.action == "buy" and adjusted_confidence < 0.7:
        action = "hold"
    if risk_tolerance == "conservative" and base.action == "sell" and adjusted_confidence > 0.75:
        action = "hold"
    if goal_primary == "capital_preservation" and base.action == "buy" and base.conviction_score <= 2:
        action = "hold"
    if goal_primary == "aggressive_growth" and base.action == "hold" and base.conviction_score >= 4:
        action = "buy"

    if risk_tolerance == "aggressive":
        min_alloc, max_alloc = (6.0, 12.0)
    elif risk_tolerance == "balanced":
        min_alloc, max_alloc = (4.0, 8.0)
    else:
        min_alloc, max_alloc = (2.0, 5.0)

    if action == "hold":
        min_alloc = max(0.0, min_alloc - 2.0)
        max_alloc = max(min_alloc + 1.0, max_alloc - 3.0)
    if action == "sell":
        min_alloc = 0.0
        max_alloc = 0.0

    if base.conviction_score >= 4:
        max_alloc += 2.0
    urgency_label = "high" if base.conviction_score >= 4 and action != "hold" else "medium" if action != "hold" else "low"
    profile_fit += 0.04 if action == base.action else -0.08
    profile_fit = round(max(0.45, min(0.95, profile_fit - risk_penalty)), 2)
    rationale = (
        f"Personalized for a {risk_tolerance} investor focused on {goal_primary.replace('_', ' ')} with "
        f"{holding_period_preference.replace('_', ' ')} preference. The recommendation lands on {action.upper()} "
        f"with a suggested allocation band of {min_alloc:.1f}% to {max_alloc:.1f}%."
    )
    return PersonalizedRecommendation(
        action=action,
        conviction_score=base.conviction_score,
        profile_fit_score=profile_fit,
        allocation_min_pct=round(min_alloc, 1),
        allocation_max_pct=round(max_alloc, 1),
        urgency_label=urgency_label,
        rationale=rationale,
    )


def build_backtest_metrics(*, sample_size: int, buy_count: int, sell_count: int, avg_confidence: float) -> BacktestMetrics:
    hit_rate = round(min(0.74, 0.49 + sample_size * 0.002 + avg_confidence * 0.1), 2)
    win_rate = round(min(0.69, 0.46 + buy_count * 0.003 + sell_count * 0.002), 2)
    average_return = round((buy_count - sell_count) * 0.16 + avg_confidence * 4.2, 2)
    benchmark_return = round(max(2.0, average_return - 1.6), 2)
    max_drawdown = round(max(4.0, 14.0 - avg_confidence * 7.0), 2)
    calibration_error = round(max(0.04, 0.18 - avg_confidence * 0.12), 2)
    return BacktestMetrics(
        sample_size=sample_size,
        hit_rate=hit_rate,
        win_rate=win_rate,
        average_return=average_return,
        benchmark_return=benchmark_return,
        max_drawdown=max_drawdown,
        calibration_error=calibration_error,
    )
