# Commercialization Package

## Product summary

Market Reaction Forecaster is a premium consumer subscription app for explicit `buy`, `hold`, and `sell` calls on a frozen large-cap tech universe. The launch posture is intentionally aggressive: consumers get clear directional calls, risk-profile-aware sizing guidance, event context, and a simulated model portfolio without brokerage execution.

## Repo and deployment info

- repo: `https://github.com/tahseen137/market-reaction-forecaster`
- deploy target: Render
- runtime: FastAPI web service + Celery worker + Postgres + Redis-compatible queue
- primary docs:
  - `README.md`
  - `docs/mvp-spec.md`
  - `docs/architecture.md`
  - `docs/business-proposal.md`
  - `docs/marketing-plan.md`
  - `docs/launch-readiness.md`

## Core features

- public landing, pricing, and legal pages
- signup, login, session auth, CSRF protection, lockouts, password reset
- trial and subscriber gating
- goals-based profile onboarding
- frozen launch universe for large-cap tech
- event library with manual-entry fallback
- recommendation feed with `buy`, `hold`, and `sell` calls
- per-symbol recommendation details with evidence, invalidation, and 1 / 5 / 20 day ranges
- watchlists
- backtest summaries and markdown exports
- personalized model portfolio
- admin operations, market refresh, and audit activity
- Stripe-ready billing endpoints and entitlement state

## Pricing page copy

### Headline

AI-powered buy, hold, and sell calls for the stocks retail investors actually obsess over.

### Subheadline

Cut through earnings noise, company news, and macro headlines with explicit calls, scenario ranges, and risk-aware sizing guidance for large-cap tech.

### Plans

- `Free`
  - delayed sample calls
  - public market pages
  - limited watchlist visibility
- `Pro Monthly`
  - `$19/month`
  - 7-day free trial
  - live recommendation feed
  - full watchlists
  - model portfolio
  - backtests and report exports
- `Pro Annual`
  - `$190/year`
  - 7-day free trial
  - same feature set as monthly
  - two months free versus monthly billing

### Proof points

- explicit `buy`, `hold`, and `sell` outputs instead of vague summaries
- profile-aware sizing guidance, not one-size-fits-all commentary
- evidence links, invalidation conditions, and benchmark context on every call
- simulated model portfolio for discipline without brokerage execution

### FAQ hooks

- Is this financial advice?
- Do you place trades for me?
- How often do recommendations update?
- Which stocks are covered?
- How are backtests shown?

## Sales and growth outline

### Positioning

Own the "AI stock calls for tech investors" niche instead of trying to be a whole-market terminal.

### ICP

- active self-directed investors
- finance-newsletter subscribers
- creator-led trading community members
- users already paying for stock screeners, charting, or premium newsletters

### Channels

- X launch threads and clipped recommendation screenshots
- Substack sponsorships and creator affiliate demos
- Product Hunt launch
- comparison pages against generic AI stock-picking products
- short-form demo videos on YouTube and TikTok

### Conversion hooks

- delayed public sample calls
- free trial
- personalized profile onboarding
- shareable markdown report exports

## Demo script

1. Land on the homepage and show the delayed sample call.
2. Sign up and acknowledge disclosures.
3. Complete the profile and show how risk tolerance changes allocation guidance.
4. Open a symbol detail page and walk through the thesis, ranges, and invalidation.
5. Show the watchlist, backtests, and model portfolio.
6. End on the pricing page and billing flow.

## Cold outbound / creator outreach

### Creator DM

```text
Built something you may actually want to demo: AI-powered buy/hold/sell calls for large-cap tech with profile-aware sizing, event context, and a simulated model portfolio. No broker layer, just a sharp research product for retail investors. If you want early access, I can send a private login and a 3-minute walkthrough.
```

### Newsletter sponsorship angle

```text
Market Reaction Forecaster helps active retail investors move from headlines to explicit buy/hold/sell calls on big tech names. The product pairs clear calls with evidence, invalidation criteria, and paper-portfolio discipline. Ideal fit for readers who already pay for research but want a faster event-driven workflow.
```

## Operator how-to

### Local run

```bash
pip install -e ".[dev]"
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

### Production setup checklist

1. Create Stripe products and copy monthly and annual price IDs.
2. Set `SESSION_SECRET` and bootstrap admin credentials.
3. Set `TWELVE_DATA_API_KEY` and `FINNHUB_API_KEY`.
4. Configure the Stripe webhook secret.
5. Deploy the Render blueprint.
6. Verify `/health`, `/ready`, signup, profile onboarding, and billing test flow.

## Release notes summary

- production FastAPI monolith
- subscription-ready auth and billing
- event ingestion adapters and deterministic recommendation engine
- backtests, model portfolio, report exports, and admin tooling
- test suite with coverage gate and migration checks
