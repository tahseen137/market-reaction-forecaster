from __future__ import annotations

from app.schemas import BacktestRunRead, RecommendationDetailRead


def build_recommendation_markdown(recommendation: RecommendationDetailRead) -> str:
    horizon_lines = "\n".join(
        f"- {item.horizon_days}d: {item.expected_return_low}% / {item.expected_return_mid}% / {item.expected_return_high}%"
        for item in recommendation.horizon_ranges
    )
    mirofish_lines = ""
    if recommendation.mirofish_analysis is not None:
        mirofish_lines = (
            f"## MiroFish Sentiment Simulation\n"
            f"- Regime: {recommendation.mirofish_analysis.regime}\n"
            f"- Aggregate sentiment: {recommendation.mirofish_analysis.aggregate_sentiment:+.2f}\n"
            f"- Consensus: {recommendation.mirofish_analysis.consensus_strength:.0%}\n"
            f"- Explanation: {recommendation.mirofish_analysis.explanation}\n"
        )
    chaos_lines = ""
    if recommendation.chaos_analysis is not None:
        chaos_lines = (
            f"## Predictability Horizon\n"
            f"- Chaos score: {recommendation.chaos_analysis.chaos_score:.2f}\n"
            f"- Horizon: {recommendation.chaos_analysis.predictability_horizon_days} days\n"
            f"- Confidence band: {recommendation.chaos_analysis.confidence_band}\n"
            f"- Explanation: {recommendation.chaos_analysis.explanation}\n"
        )
    return (
        f"# {recommendation.symbol} {recommendation.action.upper()}\n\n"
        f"Conviction: {recommendation.conviction_score}/5\n"
        f"Confidence: {recommendation.confidence_score:.0%}\n"
        f"Benchmark: {recommendation.benchmark_symbol}\n"
        f"Weight profile: {recommendation.weight_profile_name or 'baseline'}\n\n"
        f"## Thesis\n{recommendation.thesis_summary}\n\n"
        f"## Evidence\n{recommendation.evidence_summary}\n\n"
        f"## Invalidation\n{recommendation.invalidation_conditions}\n\n"
        f"{mirofish_lines}\n"
        f"{chaos_lines}\n"
        f"## Horizon Ranges\n{horizon_lines}\n"
    )


def build_backtest_markdown(backtest: BacktestRunRead) -> str:
    return (
        f"# Backtest Summary\n\n"
        f"- Scope: {backtest.scope_label}\n"
        f"- Universe version: {backtest.universe_version}\n"
        f"- Sample size: {backtest.sample_size}\n"
        f"- Hit rate: {backtest.hit_rate:.0%}\n"
        f"- Win rate: {backtest.win_rate:.0%}\n"
        f"- Average return: {backtest.average_return}%\n"
        f"- Benchmark return: {backtest.benchmark_return}%\n"
        f"- Max drawdown: {backtest.max_drawdown}%\n"
        f"- Calibration error: {backtest.calibration_error}\n"
    )
