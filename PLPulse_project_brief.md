# PLPulse — Premier League News Sentiment vs Match Outcome Pipeline

## Objective
Build an end-to-end data pipeline that ingests Premier League match results and football news/media coverage, runs NLP sentiment analysis on that coverage, and links sentiment to match outcomes and team performance — surfaced through an interactive dashboard.

**Core questions the project answers:**
1. Does pre-match/post-match media sentiment about a team correlate with their actual match performance (result, goals scored/conceded)?
2. Based on current-season form + sentiment trends, who is predicted to win the league?

Scope: Premier League only. All **live pipeline data** (matches, news, sentiment) must be the **2026–2027 season only**, starting from Matchweek 1 onward — do not ingest or display any older season's fixtures/results in the live pipeline or dashboard. Older seasons (2015–2016 through 2025–2026, or as far back as the API allows) may be used **only** as historical training data for the predictive model, kept in a clearly separate training dataset — never mixed into the live Bronze/Silver/Gold tables.

---

## Required Tech Stack (do not substitute without asking me first)

| Layer | Tool |
|---|---|
| Ingestion | dlt (Data Load Tool) |
| Streaming/events (optional stretch) | Apache Kafka (Redpanda) |
| Data Warehouse | PostgreSQL (+ pgvector extension enabled) |
| Transformation | dbt |
| Data Quality | Great Expectations |
| NLP | Hugging Face Transformers (sentiment model — general-purpose or sports-domain if available) |
| Experiment/Model Tracking | MLflow |
| Orchestration | Dagster |
| Serving Layer | FastAPI |
| Visualization | Streamlit |
| Infra as Code | Terraform (for Postgres provisioning, even if local/dockerized) |

Do not introduce Airflow, Snowflake, Soda Core, or Power BI — those were used in a prior project and this one must use a distinct stack.

---

## Data Sources

1. **Match data (live pipeline):** football-data.org API (free tier) or API-Football — fixtures, results, scorelines, matchweek, home/away, **filtered strictly to the 2026–2027 Premier League season**. Confirm the season/competition ID in the API call explicitly; do not rely on a "latest" or default endpoint that could silently return the wrong season.
2. **Match data (model training only):** the same API's historical endpoints — as many past Premier League seasons as available — used exclusively to train the predictive model. This data lives in its own training dataset/table, separate from the live Bronze/Silver/Gold pipeline.
3. **News/media coverage (live pipeline):** NewsAPI or an RSS-based scrape of football news sites (BBC Sport, Sky Sports) filtered by team name, **date-bounded to the 2026–2027 season only**. Discard or reject any article dated before the season's start.

---

## Architecture (Bronze → Silver → Gold, same medallion pattern as before)

```
┌──────────────┐     ┌──────────────────┐
│ Football API │     │  News API / RSS  │
└──────┬───────┘     └──────┬───────────┘
       │ dlt                 │ dlt
       ▼                     ▼
┌─────────────────────────────────────┐
│   BRONZE (Raw Ingestion) — Postgres  │  ◄── Great Expectations checks
└──────────────────┬──────────────────┘
                   │ dbt + Python (NLP step)
                   ▼
┌─────────────────────────────────────┐
│   SILVER (Cleaned + Scored)          │
│  silver_matches                      │
│  silver_news_articles                │
│  silver_sentiment_scores  ◄─ NLP     │
└──────────────────┬──────────────────┘
                   │ dbt
                   ▼
┌─────────────────────────────────────┐
│   GOLD (Dimensional Models)          │
│  fact_team_sentiment_performance     │
│  dim_team    dim_matchweek           │
└──────────────────┬──────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌───────────────┐     ┌───────────────┐
│   FastAPI      │     │  Streamlit    │
│  (serve data)  │     │  (dashboard)  │
└───────┬───────┘     └───────┬───────┘
        │                      │
        ▼                      │
┌────────────────────┐         │
│ Predictive Model    │◄────────┘
│ (trained offline on │  (prediction shown
│  historical seasons,│   alongside live
│  scored on live     │   sentiment/results)
│  2026-27 features)  │
│  tracked in MLflow   │
└────────────────────┘
```

Orchestration: Dagster assets/jobs manage the full flow above (ingestion → GE checks → dbt → NLP scoring → serving). Model training is a **separate, manually-triggered Dagster job** (not part of the live per-matchweek pipeline) since it only needs to rerun occasionally, not every matchweek.

---

## Task Breakdown (work through in order, do not skip ahead)

### Task 1 — Environment & Infra Setup
- Set up project structure (mirror a standard dlt+dbt+Dagster repo layout).
- Write Terraform config to provision a local/dockerized Postgres instance with pgvector enabled.
- Set up `.env.example` with placeholders for API keys (football-data.org, NewsAPI). Never commit real keys.
- **Checkpoint:** confirm Postgres is reachable and pgvector extension loads before proceeding.

### Task 2 — Bronze Layer: Ingestion
- Build a dlt pipeline to ingest Matchweek 1 (and ongoing) fixtures/results into Postgres raw schema.
- Build a second dlt pipeline to ingest news headlines/articles per PL club into Postgres raw schema.
- **Checkpoint:** query raw tables directly in Postgres to confirm row counts look sane (20 teams, expected fixture count for MW1) before moving on.

### Task 3 — Data Quality Gate
- Write Great Expectations suites for both raw tables: e.g., no null team names, valid date ranges, scoreline values are non-negative integers, expected number of fixtures per matchweek.
- **Checkpoint:** pipeline must fail loudly and stop (not silently continue) if GE checks fail. Demonstrate this by intentionally breaking a check once.

### Task 4 — Silver Layer: Cleaning + NLP Scoring
- dbt models: `silver_matches`, `silver_news_articles` — typed, deduplicated, standardized team names (must match exactly between the two sources — this is the hardest join key problem, solve it explicitly, don't hand-wave it).
- Python step (outside dbt, orchestrated by Dagster): run each news article through a Hugging Face sentiment model, output label + confidence score into `silver_sentiment_scores`.
- Log every sentiment scoring run (model version, dataset size, avg scores) to MLflow.
- **Checkpoint:** show me a sample of 10 scored articles with their sentiment labels before proceeding — confirm the scores look reasonable, not garbage.

### Task 5 — Gold Layer: Dimensional Model
- Build `dim_team`, `dim_matchweek`, and `fact_team_sentiment_performance` (one row per team per matchweek: avg sentiment score, article count, result, goals for/against, points).
- **Checkpoint:** validate that every team has a row for Matchweek 1 — no silent drops.

### Task 6 — Historical Training Dataset (separate from live pipeline)
- Ingest historical Premier League seasons (as many as the chosen API supports) via a **separate** dlt pipeline into a clearly named training schema/table (e.g., `training_historical_matches`) — must not touch or merge into the live Bronze/Silver/Gold tables from Tasks 2–5.
- Engineer features per team per matchweek: rolling form (points from last 5 games), goal difference trend, home/away split, and — where available — sentiment proxies if historical news data is feasible; otherwise train on results-only features and note this limitation clearly.
- **Checkpoint:** show row counts and a sample of the training table, and confirm zero overlap with the 2026–2027 live tables (e.g., a query proving no 2026-27 rows exist in the training table, and vice versa).

### Task 7 — Predictive Model: League Winner Prediction
- Train a model (start simple — logistic regression or gradient boosting classifier per-match, then aggregate to a season-level win-probability-per-team via simulation, e.g., Monte Carlo simulating remaining fixtures using per-match win/draw/loss probabilities) using the Task 6 historical dataset.
- Log every training run to MLflow: model type, features used, evaluation metrics (e.g., log loss, accuracy on a held-out historical season), and the final model artifact.
- Score the trained model on **current 2026–2027 live features** (from the Silver/Gold tables) to produce an updated "predicted league winner" + win probability per team, recomputed after each matchweek as new live results come in.
- Store predictions in a new Gold table, e.g., `gold_title_predictions` (team, matchweek, win probability, predicted final rank).
- **Checkpoint:** show the model's predicted probabilities sum to ~100% across all 20 teams for a given matchweek, and sanity-check that they shift sensibly after a matchweek's results are added (a team that just won a big game should not see its title probability drop).

### Task 8 — Serving Layer
- Build a FastAPI app with at least these endpoints:
  - `GET /team/{team_name}/sentiment` — sentiment trend over matchweeks
  - `GET /team/{team_name}/performance` — results + points over matchweeks
  - `GET /matchweek/{n}/summary` — league-wide sentiment vs results for that week
  - `GET /predictions/title` — current title-winner probability per team, from `gold_title_predictions`
- **Checkpoint:** test each endpoint returns real data via a local request before touching Streamlit.

### Task 9 — Dashboard
- Build a Streamlit app that calls the FastAPI endpoints (not the database directly) and shows:
  - Sentiment vs points scatter plot across teams for the current matchweek
  - Per-team sentiment trend line (extendable as more matchweeks complete)
  - Table of most positive/negative covered teams this week
  - **Title race panel:** bar chart of predicted title-winning probability per team, updated as matchweeks progress, plus a note showing which matchweek/model version the prediction is based on
- **Checkpoint:** confirm dashboard updates correctly if new matchweek data is added, and that the title-race panel changes accordingly.

### Task 10 — Orchestration
- Wrap Tasks 2–5 (ingestion → GE checks → dbt → NLP scoring) into a single Dagster job with clearly separated assets, so the whole pipeline can be re-run for each new matchweek as the season progresses.
- Set up Task 7's model training as its own separate, manually-triggered Dagster job (not run automatically every matchweek) — but the **scoring** step (applying the already-trained model to new live data) should run as part of the regular per-matchweek job.
- **Checkpoint:** run the full per-matchweek Dagster job end-to-end once, from empty live tables to a working Streamlit dashboard showing both sentiment and title predictions, with no manual intervention.

---

## Cross-Checking Rules (apply at every task)
1. After completing each task, re-read the task requirements above and confirm every bullet was actually implemented — don't mark a task done based on partial completion.
2. Do not proceed to the next task until the stated checkpoint has been verified with real output (actual query results, actual sample data, actual API response) — not assumed.
3. If a required tool from the tech stack table is not used somewhere it logically should be, flag it and explain why before substituting something else.
4. At the end of all 8 tasks, produce a summary checklist confirming which tools from the tech stack table were actually used, and where.

---

## Out of Scope (do not build these unless explicitly asked)
- Multi-league support — Premier League only.
- Kafka streaming — optional stretch goal, not required for v1.
- Betting odds integration or any gambling-related features.
- Mixing historical training-season data into the live 2026–2027 pipeline tables or dashboard views — these must remain strictly separated (see Data Sources and Task 6).
