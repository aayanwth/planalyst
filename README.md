[README.md](https://github.com/user-attachments/files/31426952/README.md)
# ⚽ PLPulse — Premier League News Sentiment vs Match Outcome Pipeline

An end-to-end data pipeline that ingests **Premier League match results** and **football news/media coverage**, runs **NLP sentiment analysis** on that coverage, and links sentiment to match outcomes and team performance — surfaced through an interactive dashboard with a **title-race prediction model**.

---

## 🎯 Core Questions

1. Does pre-match/post-match media sentiment about a team correlate with their actual match performance (result, goals scored/conceded)?
2. Based on current-season form + sentiment trends, **who is predicted to win the league**?

## 📌 Scope

- **Premier League only** — no multi-league support.
- **Live pipeline data** (matches, news, sentiment) is restricted to the **2026–2027 season, Matchweek 1 onward**. No older-season fixtures/results are ingested or displayed in the live pipeline or dashboard.
- **Historical seasons** (2015–16 through 2025–26, or as far back as the API allows) are used **only** to train the predictive model, stored in a strictly separate training dataset — never merged into the live Bronze/Silver/Gold tables.

---

## 🏗️ Architecture

Medallion architecture (Bronze → Silver → Gold), orchestrated end-to-end by Dagster:

<img width="750" height="766" alt="Screenshot 2026-08-25 211514" src="https://github.com/user-attachments/assets/fa2049ac-710f-4758-813f-f8e9addb5196" />


Orchestration split into **two Dagster jobs**:
- `matchweek_pipeline` — automated, re-run every matchweek (ingestion → GE checks → dbt → NLP scoring → model *scoring*).
- `model_training_job` — manually triggered only, since model *training* on historical data doesn't need to run every matchweek.

---

## 🧰 Tech Stack

| Layer | Tool |
|---|---|
| Ingestion | dlt (Data Load Tool) |
| Streaming/events (optional stretch) | Apache Kafka (Redpanda) |
| Data Warehouse | PostgreSQL (+ pgvector extension) |
| Transformation | dbt |
| Data Quality | Great Expectations |
| NLP | Hugging Face Transformers (`cardiffnlp/twitter-roberta-base-sentiment-latest`) |
| Experiment/Model Tracking | MLflow |
| Orchestration | Dagster |
| Serving Layer | FastAPI |
| Visualization | Streamlit |
| Infra as Code | Terraform |

> Airflow, Snowflake, Soda Core, and Power BI are intentionally **not** used — this project uses a distinct stack from prior work.

---

## 🗂️ Data Sources

| # | Source | Purpose | Notes |
|---|--------|---------|-------|
| 1 | football-data.org / API-Football | **Live pipeline** — fixtures, results, scorelines, matchweek, home/away | Filtered strictly to the 2026–2027 PL season; competition/season ID confirmed explicitly in each call (no "latest"/default endpoint) |
| 2 | Same API's historical endpoints | **Model training only** | As many past PL seasons as available, isolated in its own training dataset |
| 3 | NewsAPI / RSS (BBC Sport, Sky Sports) | **Live pipeline** — news/media coverage per club | Date-bounded to the 2026–2027 season; articles dated before season start are discarded |

---

## 📁 Repository Structure

```
.
├── PLPulse_project_brief.md      # Original project requirements/task list
├── docker-compose.yml            # Local Postgres (pgvector enabled)
├── init-db.sql                   # Creates bronze/silver/gold/training schemas + vector extension
├── pyproject.toml                # Python deps: dlt, dbt, dagster, fastapi, streamlit, xgboost, ...
├── .env / .env.example           # API keys & DB connection strings (.env gitignored)
├── .gitignore
│
├── terraform/                    # Infra as Code
│   ├── main.tf                   # Postgres provider/resources
│   ├── variables.tf              # DB username, password, port, etc.
│   ├── outputs.tf                # Connection string output
│   └── terraform.tfvars.example
│
├── planalyst/                    # Core Python package
│   ├── config.py                 # Env vars, schemas, team name mappings
│   │
│   ├── pipelines/                # dlt ingestion → bronze schema
│   │   ├── football_matches.py       # Live 2026-27 fixtures/results
│   │   ├── news_articles.py          # Live news, NewsAPI + RSS fallback
│   │   └── historical_matches.py     # Historical seasons → training schema (isolated)
│   │
│   ├── quality/                  # Great Expectations gates
│   │   ├── ge_config.py
│   │   ├── match_expectations.py
│   │   └── news_expectations.py
│   │
│   ├── nlp/
│   │   └── sentiment.py          # HF sentiment scoring → silver_sentiment_scores, logged to MLflow
│   │
│   ├── ml/
│   │   ├── features.py           # Elo, rolling points, goal diff, streaks
│   │   ├── train.py              # XGBoost training + MLflow logging
│   │   └── predict.py            # Monte Carlo simulation → gold_title_predictions
│   │
│   ├── api/                      # FastAPI serving layer
│   │   ├── main.py
│   │   ├── database.py
│   │   └── routers/
│   │
│   └── dagster_assets/           # Orchestration
│       ├── definitions.py
│       ├── jobs.py               # matchweek_pipeline, model_training_job
│       ├── resources.py
│       └── assets/
│           ├── ingestion.py
│           ├── quality.py
│           ├── transformations.py
│           ├── nlp_scoring.py
│           └── model_scoring.py
│
├── dbt_project/                  # Transformation layer
│   ├── dbt_project.yml
│   └── models/
│       ├── sources.yml
│       ├── silver/                # silver_matches, silver_news_articles
│       └── gold/                  # dim_team, dim_matchweek, fact_team_sentiment_performance
│
└── streamlit_app/                 # Dashboard
    ├── app.py                     # Title race probabilities
    ├── utils.py                   # HTTP calls to FastAPI
    └── pages/                     # Overview + Team Detail pages
```

---

## 🚀 Getting Started

### Prerequisites
- Docker & Docker Compose
- Terraform
- Python 3.10+ (managed via `pyproject.toml`)
- API keys: [football-data.org](https://www.football-data.org/) (or API-Football) and [NewsAPI](https://newsapi.org/)

### 1. Configure environment
```bash
cp .env.example .env
# fill in FOOTBALL_DATA_API_KEY, NEWSAPI_KEY, POSTGRES_* connection details
```

### 2. Provision Postgres (Terraform + Docker)
```bash
cd terraform
terraform init
terraform apply
```
This provisions the local/dockerized Postgres instance (via `docker-compose.yml` + `init-db.sql`), creating the `bronze`, `silver`, `gold`, and `training` schemas and enabling the `vector` (pgvector) extension.

**Checkpoint:** confirm Postgres is reachable and `pgvector` loads:
```sql
SELECT * FROM pg_extension WHERE extname = 'vector';
```

### 3. Install Python dependencies
```bash
pip install -e .
```

### 4. Run the live matchweek pipeline (Dagster)
```bash
dagster dev -f planalyst/dagster_assets/definitions.py
```
Trigger the `matchweek_pipeline` job from the Dagster UI (or CLI) to run ingestion → Great Expectations checks → dbt → NLP scoring → model scoring, end to end.

### 5. Train the predictive model (manual, occasional)
Trigger the separate `model_training_job` in Dagster to ingest historical seasons, engineer features, train the model, and log everything to MLflow.

### 6. Serve the API
```bash
uvicorn planalyst.api.main:app --reload
```

Available endpoints:
| Endpoint | Description |
|---|---|
| `GET /team/{team_name}/sentiment` | Sentiment trend over matchweeks |
| `GET /team/{team_name}/performance` | Results + points over matchweeks |
| `GET /matchweek/{n}/summary` | League-wide sentiment vs results for that week |
| `GET /predictions/title` | Current title-winner probability per team |

### 7. Launch the dashboard
```bash
streamlit run streamlit_app/app.py
```

The dashboard (via FastAPI, never hitting the DB directly) shows:
- Sentiment vs points scatter plot across teams for the current matchweek
- Per-team sentiment trend lines
- Table of most positive/negative covered teams this week
- **Title race panel** — bar chart of predicted title-winning probability per team, with a note on which matchweek/model version the prediction is based on

---

## 🧪 Data Quality & Separation Guarantees

- **Great Expectations** gates sit between Bronze and Silver: no null team names, valid date ranges, non-negative scorelines, expected fixture counts per matchweek. The pipeline **fails loudly and stops** on any check failure — it does not continue silently.
- **Live vs. training separation** is enforced structurally: historical data lives only in the `training` schema (e.g. `training_historical_matches`) and is ingested by a dedicated `historical_matches.py` pipeline. The live Bronze/Silver/Gold tables under `bronze`/`silver`/`gold` schemas only ever contain 2026–27 data. Overlap between the two can be verified directly:
```sql
-- Should return 0 rows both ways
SELECT * FROM training.training_historical_matches WHERE season = '2026-27';
SELECT * FROM bronze.football_matches WHERE season != '2026-27';
```
- **Team name standardization** between match data and news data is handled explicitly in `dbt_project/models/silver/` and `planalyst/config.py`, since it's the primary join key across the two sources.

---

## 🔮 Predictive Model

- **Training** (`ml/train.py`): trained on `training_historical_matches`, using engineered features from `ml/features.py` (Elo ratings, rolling points from last 5 games, goal difference trend, home/away split, win streaks). Every run — model type, features, evaluation metrics (log loss, accuracy on a held-out historical season), and the model artifact — is logged to **MLflow**.
- **Scoring** (`ml/predict.py`): applies the trained model to current 2026–27 live features and runs **1,000 Monte Carlo simulations** of remaining fixtures to compute each team's title-winning probability and predicted final rank, recomputed after each matchweek.
- **Output table:** `gold_title_predictions` (team, matchweek, win probability, predicted final rank).

---

## ✅ Cross-Checking Principles

1. Each task is verified against the full brief before being marked complete — no partial-completion sign-off.
2. Every stage's checkpoint is confirmed with **real output** (actual query results, actual sample data, actual API responses) before moving to the next stage.
3. If a required stack tool isn't used somewhere it logically should be, that's flagged and explained rather than silently substituting another tool.
4. A final tech-stack usage checklist confirms every tool in the table above was actually used, and where.

---

## 🚫 Out of Scope

- Multi-league support (Premier League only)
- Kafka/Redpanda streaming (optional stretch goal, not in v1)
- Betting odds integration or gambling-related features
- Mixing historical training-season data into the live 2026–27 pipeline tables or dashboard views

---

## 📄 License

Add your license of choice here (e.g. MIT).
