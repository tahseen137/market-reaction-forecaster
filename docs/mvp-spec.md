# MVP Spec

## Launch scope

Market Reaction Forecaster v1 is a consumer web app for explicit `buy`, `hold`, and `sell` calls on a fixed large-cap tech universe.

## Included features

- public landing page and pricing page
- signup, login, logout, password reset
- profile onboarding:
  - age band
  - investable amount band
  - goal
  - risk tolerance
  - drawdown tolerance
  - holding period
  - income stability
  - sector concentration tolerance
  - experience level
- disclosure acknowledgment gate
- delayed sample feed for public users
- paid personalized feed for trial and subscriber users
- event library
- recommendation detail pages
- backtest summary
- model portfolio
- watchlists
- Stripe-ready billing endpoints
- admin operations and activity feed

## Data sources

- Twelve Data
- Finnhub
- SEC EDGAR
- curated IR RSS feeds
- manual event entry

## Core recommendation output

Each recommendation includes:

- action: `buy`, `hold`, or `sell`
- conviction score `1-5`
- confidence score
- profile-fit score
- suggested allocation band
- 1 / 5 / 20 trading-day ranges
- thesis summary
- evidence summary
- invalidation conditions
- benchmark symbol

## Non-goals

- brokerage execution
- options
- short selling
- holdings import
- whole-market coverage

## Success criteria

- a new user can sign up and reach the dashboard without manual operator intervention
- a paid user can acknowledge disclosures, save a profile, and generate a recommendation flow in under 10 minutes
- recommendation and backtest exports are reproducible
- deployments are test-covered and migration-safe
