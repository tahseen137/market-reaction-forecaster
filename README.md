# Market Reaction Forecaster

Market Reaction Forecaster is a production-ready consumer subscription app for explicit AI-powered `buy`, `hold`, and `sell` calls on a frozen large-cap tech universe.

The launch product is deliberately aggressive:
- retail-facing
- premium subscription
- goals-based personalization
- event-driven plus daily refresh logic
- recommendations only, with no brokerage execution

## What the product does

- Public marketing site with delayed sample calls
- Account signup, login, password reset email hooks, self-serve password change, session auth, and CSRF protection
- Trial and subscription state model with Stripe-ready billing hooks
- Personalized recommendation feed driven by:
  - event classification
  - price and momentum context
  - analog density
  - risk-profile adjustment
- Manual event entry plus ingestion adapters for:
  - SEC EDGAR
  - Finnhub news
  - IR/newsroom RSS
  - Twelve Data quotes
- Backtest snapshot and model portfolio views
- Admin user management and market refresh operations
- Validation instrumentation:
  - funnel analytics for signup, profile completion, disclosure acknowledgment, watchlists, recommendation views, and checkout starts/completions
  - recommendation snapshot export
  - daily validation reports with shadow-portfolio performance
  - admin validation dashboard at `/admin/validation`
- Account-level system status with connector visibility and scheduler state
- Markdown report exports for recommendations and backtests
- Docker, Alembic, CI, and Render deployment config

## Repo layout

```text
market-reaction-forecaster/
  app/                  FastAPI app, models, services, templates, static assets
  alembic/              Database migrations
  tests/                Unit and integration tests
  docs/                 Product, business, and launch documentation
  Dockerfile
  render.yaml
  pyproject.toml
```

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Environment highlights

- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `SESSION_SECRET`
- `TWELVE_DATA_API_KEY`
- `FINNHUB_API_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_PRICE_MONTHLY`
- `STRIPE_PRICE_ANNUAL`
- `POSTMARK_SERVER_TOKEN`
- `POSTMARK_FROM_EMAIL`

See [.env.example](./.env.example) for the full list.

## Tests

```bash
pytest
```

The repo is configured to enforce:
- full unit + integration test execution
- coverage reporting
- `90%` minimum coverage in CI

## Deployment

- Local runtime uses `uvicorn` via [start.sh](./start.sh)
- Production deploy target is Render via [render.yaml](./render.yaml)
- The blueprint includes:
  - a web service
  - a background worker with the weekday refresh scheduler
  - managed Postgres
  - managed Redis-compatible key-value storage

## Documentation

- [MVP spec](./docs/mvp-spec.md)
- [Architecture](./docs/architecture.md)
- [Business proposal](./docs/business-proposal.md)
- [Marketing plan](./docs/marketing-plan.md)
- [Commercialization package](./docs/commercialization-package.md)
- [Launch readiness](./docs/launch-readiness.md)
- [Validation todo](./docs/validation-todo.md)

## Important note

This product presents model-driven research software, not guaranteed investment outcomes. It does not place trades, custody assets, or promise returns.
