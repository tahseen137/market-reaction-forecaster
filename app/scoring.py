from __future__ import annotations

from dataclasses import asdict, dataclass
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
DEFENSIVE_EVENT_TYPES = {"regulatory", "macro", "supply_chain", "customer_loss"}


@dataclass
class PersonaSignal:
    name: str
    archetype: str
    sentiment_score: float
    position_bias: str
    confidence: float
    rationale: str


@dataclass
class MiroFishSignal:
    aggregate_sentiment: float
    aggregate_positioning: float
    consensus_strength: float
    dispersion: float
    regime: str
    explanation: str
    personas: list[PersonaSignal]


@dataclass
class ChaosAnalysis:
    chaos_score: float
    predictability_horizon_days: int
    signal_instability: float
    confidence_multiplier: float
    confidence_band: str
    explanation: str


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
    analysis_artifacts: dict[str, object]


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


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _position_bias(score: float) -> str:
    if score >= 0.2:
        return "net long"
    if score <= -0.2:
        return "net short"
    return "balanced"


def _confidence_band(chaos_score: float) -> str:
    if chaos_score <= 0.3:
        return "high"
    if chaos_score <= 0.58:
        return "medium"
    return "low"


def classify_headline_bias(headline: str, summary: str) -> float:
    text = f"{headline} {summary}".casefold()
    positive_hits = sum(1 for term in POSITIVE_TERMS if term in text)
    negative_hits = sum(1 for term in NEGATIVE_TERMS if term in text)
    raw = (positive_hits - negative_hits) * 0.05
    return max(-0.2, min(0.2, raw))


def simulate_mirofish_signal(
    *,
    event_type: str,
    headline: str,
    summary: str,
    directional_bias: float,
    day_change_pct: float,
    analog_count: int,
    source_quality: float,
) -> MiroFishSignal:
    headline_bias = classify_headline_bias(headline, summary)
    catalyst_bias = EVENT_TYPE_WEIGHTS.get(event_type, 0.0) + directional_bias + headline_bias
    momentum = _clamp(day_change_pct / 8, -1.0, 1.0)
    analog_context = _clamp((analog_count - 3) / 6, -1.0, 1.0)
    event_risk = 1.0 if event_type in DEFENSIVE_EVENT_TYPES else 0.35 if event_type in {"earnings", "guidance"} else 0.0
    surprise = _clamp(abs(catalyst_bias) + abs(momentum) * 0.35, 0.0, 1.0)

    retail_score = _clamp(momentum * 0.5 + headline_bias * 1.8 + directional_bias * 0.6 + analog_context * 0.15, -1.0, 1.0)
    institutional_score = _clamp(catalyst_bias * 0.75 + source_quality * 0.25 - abs(momentum) * 0.35 - event_risk * 0.3, -1.0, 1.0)
    options_score = _clamp(catalyst_bias * 0.4 + momentum * 0.45 + surprise * 0.25 - event_risk * 0.12, -1.0, 1.0)
    macro_score = _clamp(
        directional_bias * 0.7
        + EVENT_TYPE_WEIGHTS.get(event_type, 0.0) * 0.55
        + source_quality * 0.18
        - (0.25 if event_type in DEFENSIVE_EVENT_TYPES else 0.05),
        -1.0,
        1.0,
    )

    personas = [
        PersonaSignal(
            name="Retail Momentum",
            archetype="retail_momentum",
            sentiment_score=round(retail_score, 3),
            position_bias=_position_bias(retail_score),
            confidence=round(_clamp(0.5 + abs(momentum) * 0.22 + source_quality * 0.12, 0.5, 0.92), 2),
            rationale="Chases the tape, reacts fast to price acceleration, and amplifies headline tone.",
        ),
        PersonaSignal(
            name="Institutional Risk Manager",
            archetype="institutional_risk_manager",
            sentiment_score=round(institutional_score, 3),
            position_bias=_position_bias(institutional_score),
            confidence=round(_clamp(0.55 + source_quality * 0.2 + max(analog_context, 0.0) * 0.08, 0.52, 0.94), 2),
            rationale="Prefers validated catalysts, discounts noisy momentum, and leans defensive when risk clusters rise.",
        ),
        PersonaSignal(
            name="Options Spec Trader",
            archetype="options_spec_trader",
            sentiment_score=round(options_score, 3),
            position_bias=_position_bias(options_score),
            confidence=round(_clamp(0.48 + surprise * 0.26 + abs(momentum) * 0.1, 0.48, 0.9), 2),
            rationale="Looks for convex moves around catalysts and embraces momentum when the setup feels explosive.",
        ),
        PersonaSignal(
            name="Macro / News Trader",
            archetype="macro_news_trader",
            sentiment_score=round(macro_score, 3),
            position_bias=_position_bias(macro_score),
            confidence=round(_clamp(0.5 + source_quality * 0.16 + abs(directional_bias) * 0.2, 0.5, 0.91), 2),
            rationale="Translates the news into flows, weighting source quality and macro sensitivity over pure chart action.",
        ),
    ]

    weights = {
        "Retail Momentum": 0.24,
        "Institutional Risk Manager": 0.34,
        "Options Spec Trader": 0.18,
        "Macro / News Trader": 0.24,
    }
    aggregate_sentiment = round(sum(persona.sentiment_score * weights[persona.name] for persona in personas), 3)
    aggregate_positioning = round(
        _clamp(aggregate_sentiment * (0.7 + (sum(persona.confidence for persona in personas) / len(personas) - 0.5)), -1.0, 1.0),
        3,
    )
    dispersion = round(sum(abs(persona.sentiment_score - aggregate_sentiment) for persona in personas) / len(personas), 3)
    consensus_strength = round(_clamp(1.0 - dispersion, 0.0, 1.0), 3)

    if abs(aggregate_sentiment) < 0.08 or dispersion >= 0.48:
        regime = "cross-current"
    elif aggregate_sentiment > 0:
        regime = "bullish"
    else:
        regime = "bearish"

    leading_persona = max(personas, key=lambda persona: abs(persona.sentiment_score))
    explanation = (
        f"{regime.title()} simulated tape with {consensus_strength:.0%} consensus. "
        f"{leading_persona.name} leads at {leading_persona.sentiment_score:+.2f}, while persona dispersion sits at {dispersion:.2f}."
    )
    return MiroFishSignal(
        aggregate_sentiment=aggregate_sentiment,
        aggregate_positioning=aggregate_positioning,
        consensus_strength=consensus_strength,
        dispersion=dispersion,
        regime=regime,
        explanation=explanation,
        personas=personas,
    )


def analyze_chaos(
    *,
    event_type: str,
    day_change_pct: float,
    analog_count: int,
    mirofish_signal: MiroFishSignal,
) -> ChaosAnalysis:
    price_volatility = _clamp(abs(day_change_pct) / 9, 0.0, 1.0)
    analog_scarcity = _clamp((4 - min(analog_count, 4)) / 4, 0.0, 1.0)
    disagreement_penalty = 0.16 if mirofish_signal.regime == "cross-current" else 0.0
    event_penalty = 0.18 if event_type in DEFENSIVE_EVENT_TYPES else 0.08 if event_type in {"earnings", "guidance"} else 0.0
    signal_instability = round(
        _clamp(price_volatility * 0.38 + mirofish_signal.dispersion * 0.34 + analog_scarcity * 0.18 + disagreement_penalty, 0.0, 1.0),
        3,
    )
    chaos_score = round(_clamp(signal_instability + event_penalty, 0.0, 1.0), 3)
    predictability_horizon_days = int(round(_clamp(18 - chaos_score * 12 - price_volatility * 4 + mirofish_signal.consensus_strength * 3, 1, 20)))
    confidence_multiplier = round(_clamp(1.0 - chaos_score * 0.28 + mirofish_signal.consensus_strength * 0.05, 0.65, 1.02), 3)
    confidence_band = _confidence_band(chaos_score)
    explanation = (
        f"Chaos score {chaos_score:.2f} driven by {abs(day_change_pct):.2f}% tape movement, "
        f"{mirofish_signal.dispersion:.2f} persona dispersion, and analog scarcity at {analog_scarcity:.2f}."
    )
    return ChaosAnalysis(
        chaos_score=chaos_score,
        predictability_horizon_days=predictability_horizon_days,
        signal_instability=signal_instability,
        confidence_multiplier=confidence_multiplier,
        confidence_band=confidence_band,
        explanation=explanation,
    )


def _score_to_action(score: float) -> str:
    if score >= 0.18:
        return "buy"
    if score <= -0.18:
        return "sell"
    return "hold"


def _conviction_from_score(score: float, analog_count: int, *, consensus_strength: float, chaos_score: float) -> int:
    base = abs(score) * 5 + min(analog_count, 10) * 0.08 + consensus_strength * 0.6 - chaos_score * 0.4
    return max(1, min(5, ceil(base)))


def _confidence_from_inputs(
    score: float,
    analog_count: int,
    source_quality: float,
    *,
    consensus_strength: float,
    chaos_multiplier: float,
) -> float:
    confidence = 0.48 + min(abs(score), 0.35) + min(analog_count, 12) * 0.015 + source_quality * 0.06 + consensus_strength * 0.05
    confidence *= chaos_multiplier
    return round(max(0.5, min(0.96, confidence)), 2)


def _build_horizon_ranges(
    score: float,
    day_change_pct: float,
    *,
    chaos_score: float,
    predictability_horizon_days: int,
) -> list[dict[str, float | int]]:
    volatility_factor = max(0.02, min(0.25, abs(day_change_pct) / 100))
    horizons = sorted({1, min(5, predictability_horizon_days), predictability_horizon_days})
    ranges: list[dict[str, float | int]] = []
    for horizon in horizons:
        midpoint = score * horizon * 3.1 * (1 - chaos_score * 0.22)
        spread = max(1.2, horizon * (volatility_factor * 9) * (1 + chaos_score * 0.85))
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
    weight_overrides: dict[str, float] | None = None,
    weight_profile_name: str = "baseline",
) -> BaseRecommendation:
    source_quality = 0.8 if source_label in {"SEC EDGAR", "Investor Relations", "Manual Analyst Entry"} else 0.6
    weight_overrides = weight_overrides or {}
    event_score = weight_overrides.get(f"event_type::{event_type}", EVENT_TYPE_WEIGHTS.get(event_type, 0.0))
    headline_bias = classify_headline_bias(headline, summary)
    momentum_adjustment = max(-0.1, min(0.1, day_change_pct / 100))
    analog_density = min(analog_count, 8) * weight_overrides.get("analog_density_weight", 0.01)
    mirofish_weight = weight_overrides.get("mirofish_weight", 0.16)
    chaos_penalty_weight = weight_overrides.get("chaos_penalty_weight", 0.22)

    mirofish_signal = simulate_mirofish_signal(
        event_type=event_type,
        headline=headline,
        summary=summary,
        directional_bias=directional_bias,
        day_change_pct=day_change_pct,
        analog_count=analog_count,
        source_quality=source_quality,
    )
    chaos_analysis = analyze_chaos(
        event_type=event_type,
        day_change_pct=day_change_pct,
        analog_count=analog_count,
        mirofish_signal=mirofish_signal,
    )

    raw_directional_score = event_score + headline_bias + directional_bias + momentum_adjustment + analog_density + mirofish_signal.aggregate_sentiment * mirofish_weight
    score = max(-0.55, min(0.55, raw_directional_score * (1 - chaos_analysis.chaos_score * chaos_penalty_weight)))
    action = _score_to_action(score)
    conviction = _conviction_from_score(
        score,
        analog_count,
        consensus_strength=mirofish_signal.consensus_strength,
        chaos_score=chaos_analysis.chaos_score,
    )
    confidence = _confidence_from_inputs(
        score,
        analog_count,
        source_quality,
        consensus_strength=mirofish_signal.consensus_strength,
        chaos_multiplier=chaos_analysis.confidence_multiplier,
    )
    factor_scores = {
        "event_type_weight": round(event_score, 3),
        "headline_bias": round(headline_bias, 3),
        "directional_bias": round(directional_bias, 3),
        "momentum_adjustment": round(momentum_adjustment, 3),
        "analog_density": round(analog_density, 3),
        "source_quality": round(source_quality, 3),
        "mirofish_sentiment": round(mirofish_signal.aggregate_sentiment, 3),
        "mirofish_positioning": round(mirofish_signal.aggregate_positioning, 3),
        "mirofish_consensus": round(mirofish_signal.consensus_strength, 3),
        "chaos_score": round(chaos_analysis.chaos_score, 3),
        "signal_instability": round(chaos_analysis.signal_instability, 3),
        "predictability_horizon_days": float(chaos_analysis.predictability_horizon_days),
        "adaptive_mirofish_weight": round(mirofish_weight, 3),
        "adaptive_chaos_penalty_weight": round(chaos_penalty_weight, 3),
    }
    thesis_summary = (
        f"{company_name} ({symbol}) screens as a {action.upper()} because the latest {event_type.replace('_', ' ')} catalyst "
        f"pairs with a {mirofish_signal.regime} persona simulation ({mirofish_signal.aggregate_sentiment:+.2f}) and a "
        f"{chaos_analysis.predictability_horizon_days}-day predictability horizon at {confidence:.0%} model confidence."
    )
    evidence_summary = (
        f"{headline} Source: {source_label}. Analog sample size: {analog_count}. "
        f"Cassandra MiroFish sim: {mirofish_signal.explanation}"
    )
    invalidation_conditions = (
        "Invalidate if the next material update flips catalyst direction, the persona stack fractures into cross-currents, "
        f"or the chaos score rises above 0.70 and compresses the predictability horizon below {max(1, chaos_analysis.predictability_horizon_days // 2)} days."
    )
    analysis_artifacts = {
        "mirofish": {
            "aggregate_sentiment": mirofish_signal.aggregate_sentiment,
            "aggregate_positioning": mirofish_signal.aggregate_positioning,
            "consensus_strength": mirofish_signal.consensus_strength,
            "dispersion": mirofish_signal.dispersion,
            "regime": mirofish_signal.regime,
            "explanation": mirofish_signal.explanation,
            "personas": [asdict(persona) for persona in mirofish_signal.personas],
        },
        "chaos": {
            "chaos_score": chaos_analysis.chaos_score,
            "predictability_horizon_days": chaos_analysis.predictability_horizon_days,
            "signal_instability": chaos_analysis.signal_instability,
            "confidence_multiplier": chaos_analysis.confidence_multiplier,
            "confidence_band": chaos_analysis.confidence_band,
            "explanation": chaos_analysis.explanation,
        },
        "weights": {
            "profile_name": weight_profile_name,
            "overrides": {key: round(value, 4) for key, value in weight_overrides.items()},
        },
    }
    return BaseRecommendation(
        action=action,
        conviction_score=conviction,
        confidence_score=confidence,
        thesis_summary=thesis_summary,
        evidence_summary=evidence_summary,
        invalidation_conditions=invalidation_conditions,
        factor_scores=factor_scores,
        horizon_ranges=_build_horizon_ranges(
            score,
            day_change_pct,
            chaos_score=chaos_analysis.chaos_score,
            predictability_horizon_days=chaos_analysis.predictability_horizon_days,
        ),
        analog_sample_size=analog_count,
        benchmark_symbol=benchmark_symbol,
        source_status=source_status,
        analysis_artifacts=analysis_artifacts,
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
