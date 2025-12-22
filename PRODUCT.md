# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
Delegated: the user left the choice to the assistant, which chose to keep Streamlit (restyled with custom CSS and Plotly) because the Dockerfile, healthchecks, CI and the FastAPI serving layer all assume it. A separate custom frontend was the alternative.

## Users
Two audiences, both confirmed: recruiters/interviewers who skim the dashboard for a minute or two to judge the ML and data-engineering work, and football fans checking title odds, team form and fan sentiment. Both need a fast first read; neither is assumed to know the model internals.

## Product Purpose
PLanalyst turns Premier League results and news coverage into title-race probabilities and a sentiment-versus-performance view per club and matchweek. Success: a visitor understands within seconds who is likely to win the title, how the model arrived at that, and how press sentiment tracks results.

## Positioning
It pairs a walk-forward-evaluated match model (Elo, Poisson, XGBoost blend with calibration and bootstrap comparisons) with news sentiment scored per club per matchweek, and reports honestly where data is thin.

## Operating Context
Reads the Gold tables through a FastAPI layer (`/predictions/*`, `/team/*`, `/matchweek/*`). Data comes from football-data.org, historical CSV results, the Guardian Open Platform and GDELT news, scored with a CardiffNLP RoBERTa sentiment model. Dashboard pages today: Matchweek Overview, Team Detail, Title Race, Fixtures & Accuracy, Model Evaluation (renders docs/model_evaluation.md). Runs locally via Docker Compose; host ports are overridable.

## Capabilities and Constraints
- Season 2026-27 is live; the database has 5 played matchweeks and about 2,857 scored articles (1 before the Guardian/GDELT switch). Some teams have only a handful of articles in a week; the UI must not rank or imply precision on thin data.
- Sentiment is not a training feature (no historical news archive).
- Title-race backtest has only 6 champion outcomes; claims must stay modest.
- Must keep working inside the existing dashboard Docker image and read data only through the API.

## Brand Commitments
Name: PLanalyst. No logo or brand assets exist.
Visual direction (user-chosen, 2026-10-06, superseding an earlier choice of plain dark glass): "Midnight Transit", a midnight-blue enamel ground with porcelain-white ticks and bright metro-line inks, where the club being followed burns brightest and the rest dim; plus restrained effects (animated counters, glow on the followed club, gradient fills, live-status pulse, hover states). Navigation and controls stay standard Streamlit/web components. Quality references, assistant-named and open to correction: Linear and Vercel Analytics for density and restraint, FotMob and Sofascore for football data presentation.

## Evidence on Hand
Real data and reports exist: docs/model_evaluation.md and figures in docs/img/, docs/model_card.md, docs/sentiment_correlation.md. No testimonials, users or traffic figures exist; none may be invented.

## Product Principles
- Show the answer first (who is favourite), then the evidence behind it.
- Never present thin or empty data as a finding; label confidence and sample size.
- Every chart earns its place by answering a question a fan or a reviewer would ask.
- Be honest about model limits; credibility is the portfolio asset.
- One data source of truth: the API, not ad-hoc database reads.

## Accessibility & Inclusion
No product-specific requirement established. Charts should not rely on colour alone.
