# Market Reaction Forecaster

Market Reaction Forecaster is an MVP blueprint for an event-driven research platform that estimates how markets may react to breaking news, filings, earnings commentary, policy shifts, and competitive moves.

The product combines:

- event ingestion from structured and unstructured sources,
- simulation-driven reaction modeling inspired by MiroFish,
- a forecast scoring and calibration layer,
- and an autoresearch-style model improvement loop for paper-trading and backtest evaluation.

## MVP outcomes

- Ingest a market-moving event and attach it to a watchlist or ticker.
- Generate scenario-based forecasts across short and medium horizons.
- Show confidence, uncertainty drivers, and evidence traces.
- Track backtest performance and paper portfolio outcomes.
- Improve scoring logic over time from historical event windows.

## Repo layout

```text
market-reaction-forecaster/
  apps/
    api/                 FastAPI starter for the MVP backend
    web/                 Placeholder for the future Next.js frontend
  docs/
    mvp-spec.md
    architecture.md
    business-proposal.md
```

## Quick start

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API explorer.

## Docs

- [MVP spec](docs/mvp-spec.md)
- [Architecture](docs/architecture.md)
- [Business proposal](docs/business-proposal.md)

## Important note

This product is designed as a research and decision-support system. It should not be marketed as guaranteed investment advice, and any live deployment needs compliance, data licensing, and risk controls.

