from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(
    title="Market Reaction Forecaster API",
    version="0.1.0",
    description="Starter API for event-driven market forecasting workflows.",
)


class EventAnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=12)
    event_type: Literal["earnings", "guidance_change", "mna", "regulatory", "product_launch", "macro"]
    headline: str = Field(..., min_length=10, max_length=240)
    thesis: str = Field(..., min_length=20, max_length=2000)
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 20])


class HorizonForecast(BaseModel):
    horizon_days: int
    expected_return_low: float
    expected_return_mid: float
    expected_return_high: float


class ForecastResponse(BaseModel):
    id: str
    ticker: str
    direction: Literal["bullish", "neutral", "bearish"]
    confidence_score: float
    uncertainty_notes: list[str]
    horizons: list[HorizonForecast]
    created_at: datetime


forecast_store: dict[str, ForecastResponse] = {}


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/events/analyze", response_model=ForecastResponse)
def analyze_event(payload: EventAnalyzeRequest) -> ForecastResponse:
    horizons = [
        HorizonForecast(
            horizon_days=days,
            expected_return_low=round(-0.8 * days, 2),
            expected_return_mid=round(0.35 * days, 2),
            expected_return_high=round(1.1 * days, 2),
        )
        for days in payload.horizons
    ]
    direction: Literal["bullish", "neutral", "bearish"] = "bullish"
    if payload.event_type == "regulatory":
        direction = "neutral"

    forecast = ForecastResponse(
        id=str(uuid4()),
        ticker=payload.ticker.upper(),
        direction=direction,
        confidence_score=0.61,
        uncertainty_notes=[
            "Limited analog density for this exact event type.",
            "Short-horizon volatility may dominate headline effects.",
            "Confidence should be downgraded if macro regime shifts intraday.",
        ],
        horizons=horizons,
        created_at=datetime.now(UTC),
    )
    forecast_store[forecast.id] = forecast
    return forecast


@app.get("/v1/forecasts/{forecast_id}", response_model=ForecastResponse)
def get_forecast(forecast_id: str) -> ForecastResponse:
    if forecast_id not in forecast_store:
        raise HTTPException(status_code=404, detail="Forecast not found")
    return forecast_store[forecast_id]


@app.get("/v1/backtests/summary")
def backtest_summary() -> dict[str, float | str]:
    return {
        "coverage_universe": "Semiconductor pilot basket",
        "benchmark": "SOXX",
        "sample_events": 124,
        "directional_hit_rate": 0.58,
        "calibration_error": 0.09,
        "paper_portfolio_return": 0.12,
        "benchmark_return": 0.08,
    }

