# Thesis Validation Todo

Market Reaction Forecaster should be validated as both:
- a product people want to use and pay for
- a forecasting system that adds value beyond simple baselines

This checklist is the working source of truth for validation.

## Core thesis

We believe self-directed investors will pay for a focused large-cap tech product that:
- turns news and filings into explicit `buy` / `hold` / `sell` calls
- explains those calls with evidence and invalidation conditions
- improves investor decision quality versus headline-driven trading

## Success criteria

### Product validation

- [ ] At least `25` qualified users complete signup and profile onboarding
- [ ] At least `10` users return on `3+` separate days within `14` days
- [ ] At least `5` users create or use a watchlist
- [ ] At least `5` users view backtests or model portfolio pages
- [ ] At least `3` users start checkout
- [ ] At least `1-3` users convert to a paid subscription
- [ ] At least `5` users give structured feedback on usefulness and trust

### Forecast validation

- [x] Every recommendation snapshot is stored with timestamp, evidence, model version, and profile context
- [x] A daily shadow portfolio is generated and archived
- [x] Recommendation outcomes are compared with `SOXX` and a simple baseline
- [x] `1`, `5`, and `20` day results are measured separately
- [x] Calibration is tracked so high-confidence calls are meaningfully better than low-confidence calls
- [ ] Buy / hold / sell outputs outperform a naive baseline on at least one useful metric

## Validation metrics

### Product metrics

- signup conversion
- onboarding completion rate
- day-1 / day-7 / day-14 retention
- watchlist creation rate
- recommendation detail click-through rate
- checkout start rate
- paid conversion rate
- cancellation rate

### Forecast metrics

- hit rate by action
- average forward return by action
- excess return versus `SOXX`
- Brier score for directional correctness
- calibration by confidence bucket
- max drawdown of the shadow portfolio
- turnover and average holding period

## Required baselines

We do not validate performance against vibes. We validate against baselines.

- [ ] Baseline A: `hold everything / benchmark = SOXX`
- [ ] Baseline B: `buy on positive event bias, sell on negative event bias`
- [ ] Baseline C: `always hold`
- [ ] Baseline D: `equal-weight top market-cap large-cap tech basket`

## Experiment plan

### Phase 1: Instrumentation and data hygiene

- [x] add a daily validation export of all recommendation snapshots
- [ ] add a daily shadow-portfolio export with entry, exit, and PnL
- [x] add basic funnel tracking for signup, onboarding, watchlist, checkout
- [ ] add a manual feedback capture field on recommendation detail pages
- [x] create a validation spreadsheet or dashboard from the exports

### Phase 2: Offline forecast validation

- [x] replay the stored event set and score results for `1`, `5`, and `20` day horizons
- [ ] compare model outputs against all baselines
- [ ] split results by event type
- [x] split results by confidence bucket
- [ ] identify where the model is noisy, overconfident, or unhelpful

### Phase 3: Live shadow validation

- [ ] run the product daily with no user intervention for `2-4` weeks
- [ ] archive the top `5-10` daily live calls
- [ ] track live paper performance versus `SOXX`
- [ ] track whether high-conviction calls actually outperform lower-conviction calls
- [ ] review failures weekly and tag root causes

### Phase 4: User validation

- [ ] recruit `10-15` self-directed investors
- [ ] ask each tester to use the app for one real market week
- [ ] collect `5` structured interviews
- [ ] ask what they trusted, what they ignored, and what they would pay for
- [ ] test if users prefer recommendation feed, watchlists, backtests, or model portfolio as the primary hook

### Phase 5: Monetization validation

- [ ] turn on Stripe checkout in production
- [ ] verify the full purchase and webhook flow with a real transaction or test customer
- [ ] run a pricing test between monthly and annual emphasis
- [ ] track free-to-paid conversion
- [ ] track why users drop before checkout

## Go / no-go thresholds

We should consider the thesis validated only if both product and forecast signals are positive.

- [ ] Users repeatedly come back without being manually pushed every day
- [ ] Users explicitly say the product changes how they act on market news
- [ ] Paid conversion happens from real traffic, not only from friends
- [ ] The model beats at least one serious baseline in live shadow results
- [ ] The best-performing slices are clear enough to guide product focus

## Immediate next actions

- [x] enable product analytics and checkout funnel tracking
- [x] log all recommendation snapshots for validation review
- [ ] run the first `14` day live shadow portfolio
- [ ] recruit the first `10` testers
- [ ] conduct the first `5` feedback calls
- [ ] review results and decide whether to narrow the universe, event types, or recommendation style

## Current tooling

- Admin validation dashboard: `/admin/validation`
- Summary API: `/api/admin/validation/summary`
- Snapshot export: `/api/admin/validation/recommendation-snapshots.csv`
- Daily report export: `/api/admin/validation/reports.csv`
- Live validation runner CLI: `python -m app.validation_cli --reason manual-check --top-calls 5`
- Live validation archive list: `/api/admin/cassandra/validation/runs`
- Live validation archive trigger: `POST /api/admin/cassandra/validation/run`

## Notes

- We are validating decision usefulness first, not proving institutional-grade alpha.
- If users love the workflow but forecast quality is weak, we can reposition around research speed.
- If the model looks promising but users do not convert, pricing or positioning is wrong even if the signal is decent.
