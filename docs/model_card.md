# Model card: PLanalyst forecasts

Numbers are deliberately not copied here. Every metric lives in the generated
[`model_evaluation.md`](model_evaluation.md) (walk-forward results, confidence intervals,
calibration, title-race backtest) and in the dashboard's **Fixtures & Accuracy** page (live record).

## What it predicts

| Output | Definition |
|---|---|
| Fixture forecast | `[P(home win), P(draw), P(away win)]` for every unplayed Premier League fixture |
| Title / top-4 / relegation probability | Share of 1,000 Monte Carlo simulations of the rest of the season in which a team wins the league, finishes in the top four, or finishes in the bottom three |
| Points range | 10th to 90th percentile of simulated final points |

**Intended use:** a portfolio and learning project showing an end-to-end forecasting pipeline,
including honest evaluation. **Not intended for** betting, wagering or any decision with financial
consequences; the models are not better than simple rating systems (see below), and odds data is
deliberately out of scope.

## How the forecast is built

Three independent estimators of the same match, averaged with equal weights:

1. **XGBoost** on team-level features known before kick-off: Elo rating and gap, rolling 5-match
   points and goals, season points / goal difference / position, win rate, win streak, venue.
2. **Elo** ratings with home advantage, updated by result and goal margin. Parameters were chosen
   on validation seasons (home advantage and draw rate mattered; season regression and the
   promoted-team start rating did not).
3. **Poisson goals model**: attack, defence and home effect per club, ridge-regularised and
   weighted toward recent seasons.

Fixture probabilities feed the season simulation; winning margins are sampled from the
empirical distribution of past results so goal-difference tiebreaks are realistic.

## Data

- **Training / evaluation:** Premier League results 2015-16 to 2025-26 (4,180 matches, football-data.org
  plus the football-data.co.uk result CSVs; the two sources agree exactly where they overlap).
  Only final scores and dates are used.
- **Live:** football-data.org fixtures and results for the current season, ingested by dlt.
- **Not used by the match model:** news sentiment. There is no historical news archive, so it cannot
  be a training feature; sentiment is studied separately (`sentiment_correlation.md`).

## How it was evaluated

Walk-forward: each test season is predicted using only earlier seasons. Settings (Elo, Poisson, XGBoost,
blend) were selected on validation seasons 2018-19, which do not overlap the test seasons 2020-21 to
2025-26. Metrics are log loss, ranked probability score, Brier score and accuracy, with paired
bootstrap intervals for comparisons. Leakage is covered by tests (changing a future result must not
change an earlier prediction).

## Known limitations

- **Close to the baselines.** On the test seasons the blend is statistically indistinguishable from
  logistic regression on the Elo gap and from the Elo formula alone. Form features add nothing
  measurable on top of Elo. Football outcomes are noisy and ratings capture most of what is predictable.
- **Draws are hard.** Predicted draw probability varies little between fixtures.
- **One champion per season.** The title-race backtest has six outcomes, so it can expose a broken
  simulator but cannot rank close alternatives. Poisson-only scored best there while being the weakest
  match-level model; that is suggestive, not established.
- **Static strengths in the simulation.** Team form is held fixed over the remaining fixtures and
  team strength is treated as known, which makes title odds more confident than they should be.
- **2020-21 (no crowds)** is an outlier season; home advantage was close to zero that year.
- **Small live sample.** Live accuracy needs many matchweeks before it says anything.
- **No injuries, line-ups, schedule congestion or expected-goals data.**
