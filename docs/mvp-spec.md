# MVP Spec

## Product vision

Help research teams answer:

> "Given this event, what is the most likely market reaction over the next 1, 5, and 20 trading days, and how confident should we be?"

The MVP is intentionally scoped to decision support, paper trading, and analyst workflow acceleration before any live trading workflow.

## Core users

- Boutique hedge funds and family offices
- Sell-side and independent research teams
- Corporate strategy and investor relations teams
- Sector-focused analysts tracking event-heavy industries

## Jobs to be done

- Detect and structure market-moving events quickly.
- Turn a raw event into a forecast with assumptions and confidence.
- Compare how similar events behaved historically.
- Track where the system helps and where it fails.
- Maintain a paper-trading layer before any real capital is deployed.

## MVP feature set

### 1. Event ingestion and normalization

- Accept inputs from:
  - news headlines,
  - SEC filings,
  - earnings transcripts,
  - analyst notes,
  - policy announcements.
- Normalize events into a common schema:
  - ticker or basket,
  - event type,
  - entities involved,
  - time horizon,
  - thesis summary,
  - supporting evidence.

### 2. Watchlists and coverage maps

- Create watchlists by ticker, sector, or theme.
- Map events to:
  - company,
  - sector,
  - competitors,
  - suppliers,
  - regulators,
  - consumers.
- Show what changed versus the previous event snapshot.

### 3. Scenario simulation

- Generate best/base/worst-case reactions for each event.
- Simulate how investors, media, regulators, competitors, and customers may respond.
- Score likely outcomes by horizon:
  - 1 day,
  - 5 trading days,
  - 20 trading days.

### 4. Forecast scoring and confidence

- Output directional view:
  - bullish,
  - neutral,
  - bearish.
- Output probabilistic ranges with uncertainty notes.
- Display confidence drivers:
  - source quality,
  - event novelty,
  - historical analog density,
  - model agreement,
  - market regime fit.

### 5. Evidence and explainability

- Trace each forecast back to source documents and assumptions.
- Preserve the simulation narrative for analyst review.
- Expose the top factors that changed the score.

### 6. Backtest and paper portfolio

- Replay historical event windows.
- Track hit rate, calibration, drawdown, and regime performance.
- Maintain a paper portfolio that converts forecasts into hypothetical positions with sizing rules.

### 7. Model improvement loop

- Capture accepted and rejected forecasts.
- Use an autoresearch-style offline loop to improve:
  - event classifiers,
  - scoring prompts,
  - lightweight return models,
  - confidence calibration.

## Good features for V1.5 or V2

- Real-time alerting from premium news feeds.
- Multi-asset coverage for FX, rates, and crypto.
- Portfolio optimizer and hedging suggestions.
- Analyst collaboration threads and approval workflows.
- Compliance review and restricted-list controls.

## Non-goals for the MVP

- Retail trading app workflows.
- Fully automated live execution.
- Universal market coverage from day one.
- High-frequency trading.
- Claims of guaranteed alpha.

## Success metrics

- Analysts can go from event detection to forecast in under 10 minutes.
- Calibration error improves over each quarterly retraining cycle.
- Paper portfolio decisions are explainable and reproducible.
- At least one narrow coverage area shows repeatable edge over a passive benchmark in backtests.

## MVP delivery milestones

### Phase 1

- Manual event input
- Ticker mapping
- Base scenario engine
- Report export

### Phase 2

- Historical replay
- confidence dashboard
- watchlists
- paper portfolio

### Phase 3

- automated ingestion
- model optimization loop
- team permissions
- premium data integrations

