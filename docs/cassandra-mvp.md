# Cassandra MVP (Monday-testable)

This repo now ships a pragmatic local Cassandra layer on top of the original forecaster.

## What's new

### 1. MiroFish-style sentiment simulation
- Deterministic persona stack:
  - Retail Momentum
  - Institutional Risk Manager
  - Options Spec Trader
  - Macro / News Trader
- Produces:
  - aggregate sentiment
  - aggregate positioning
  - consensus / dispersion
  - per-persona explanation artifacts
- Stored on each `recommendation_snapshots.analysis_artifacts` record and exposed in API/UI/reporting.

### 2. Chaos / predictability-horizon analysis
- Quantifies signal instability from:
  - tape volatility
  - persona disagreement
  - analog scarcity
  - defensive catalyst risk
- Produces:
  - chaos score
  - confidence band
  - predictability horizon (days)
- Feeds recommendation confidence and portfolio horizon sizing.

### 3. Karpathy-style AutoResearch loop
- Deterministic local evaluator over resolved outcomes (or bootstrap snapshot state if no resolved outcomes exist yet).
- Emits updated weights + recommendations to:
  - `data/uploads/cassandra/autoresearch-latest.json`
  - or your configured `UPLOADS_DIR/cassandra/autoresearch-latest.json`
- Example artifact: `docs/examples/cassandra-autoresearch-example.json`

## How to run

```bash
uv python install 3.11
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install '.[dev]'
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

## Run AutoResearch manually

```bash
source .venv/bin/activate
python -m app.autoresearch_cli
```

The CLI seeds baseline demo content on a fresh local database, refreshes validation state, and writes a deterministic artifact.

## Useful endpoints
- `GET /api/recommendations/{symbol}`
- `GET /api/recommendations/{symbol}/report.md`
- `GET /api/admin/validation/summary`
- `GET /api/admin/cassandra/autoresearch`
- `POST /api/admin/cassandra/autoresearch/run`
