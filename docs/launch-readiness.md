# Launch Readiness

## Product readiness

- public landing, pricing, legal, auth, dashboard, backtest, portfolio, account, and admin pages are implemented
- public sample feed and paid recommendation flows are separate
- recommendation detail and report export endpoints are live
- admin market-refresh and manual-event flows are in place
- account page includes self-serve password change plus live connector and scheduler status
- commercialization package is included for pricing, deck, and outreach handoff

## Operational readiness

- Dockerfile present
- Alembic migration present
- Render blueprint present
- worker config present
- weekday market refresh scheduler present
- `.env.example` updated
- CI enforces tests plus `90%` coverage minimum

## Quality status

- `25` tests passing
- `91.94%` Python coverage
- migration test present
- worker/task entrypoint test present
- scheduler config test present
- password-reset delivery test present
- Docker image build verified
- container `/health` and `/ready` smoke checks verified

## Required secrets before production deploy

- `BOOTSTRAP_ADMIN_PASSWORD`
- `SESSION_SECRET`
- `TWELVE_DATA_API_KEY`
- `FINNHUB_API_KEY`
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_PRICE_MONTHLY`
- `STRIPE_PRICE_ANNUAL`
- `STRIPE_WEBHOOK_SECRET`
- `POSTMARK_SERVER_TOKEN`
- `POSTMARK_FROM_EMAIL`

## Recommended next operator tasks

- configure Stripe products and webhook
- configure Postmark to enable live password-reset email delivery
- set final bootstrap admin password and rotate after first login
- connect real data-provider keys before public launch
