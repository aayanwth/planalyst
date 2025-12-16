# PLanalyst Project Structure

This document provides a comprehensive overview of the files and directories in the PLanalyst project, explaining the purpose of each component within the data pipeline and application architecture.

## 📁 Root Directory

*   **`PLPulse_project_brief.md`**: The original project requirements and task list that guided the development of this repository.
*   **`docker-compose.yml`**: Docker configuration file that spins up the local PostgreSQL database (with `pgvector` enabled) required for the project.
*   **`init-db.sql`**: SQL script executed when the PostgreSQL Docker container starts. It initializes the required database schemas (`bronze`, `silver`, `gold`, `training`) and enables the `vector` extension.
*   **`pyproject.toml`**: The standard Python project configuration file. It lists all the dependencies (like `dlt`, `dbt`, `dagster`, `fastapi`, `streamlit`, `xgboost`) and metadata for the project.
*   **`.env` / `.env.example`**: Stores environment variables (like API keys for football-data.org and NewsAPI, and database connection strings). `.env` is ignored by Git to keep secrets safe.
*   **`.gitignore`**: Tells Git which files and directories to ignore (e.g., virtual environments, compiled Python files, MLflow artifacts).

---

## 📁 `terraform/` (Infrastructure as Code)
Manages the infrastructure setup (even for local dockerized setups, this defines the desired state).
*   **`main.tf`**: The primary Terraform configuration file that defines the PostgreSQL database provider and resources.
*   **`variables.tf`**: Defines the input variables (like DB username, password, port) that Terraform expects.
*   **`outputs.tf`**: Defines what information Terraform should output to the console after a successful apply (e.g., the database connection string).
*   **`terraform.tfvars.example`**: A template for passing actual values into the Terraform variables.

---

## 📁 `planalyst/` (Core Python Package)
This is the heart of the project, containing the logic for ingestion, quality, machine learning, and orchestration.

*   **`config.py`**: Centralized configuration file. It loads environment variables and defines shared constants (like database schemas and team name mappings) used across the entire package.

### ↳ `pipelines/` (Data Ingestion Layer)
Uses `dlt` (Data Load Tool) to ingest data from external APIs into the Postgres `bronze` schema.
*   **`football_matches.py`**: Ingests live match fixtures and results for the current (2026-27) Premier League season from the football-data.org API.
*   **`news_articles.py`**: Ingests recent football news articles related to Premier League teams from NewsAPI (with an RSS fallback), strictly bounded to the current season.
*   **`historical_matches.py`**: A completely separate pipeline that ingests older, historical Premier League seasons specifically for training the machine learning model. It writes to the isolated `training` schema.

### ↳ `quality/` (Data Quality Gates)
Uses `Great Expectations` to ensure the ingested data is valid before downstream processing.
*   **`ge_config.py`**: Sets up the Great Expectations data context and connects it to the Postgres database.
*   **`match_expectations.py`**: Defines rules for the match data (e.g., scorelines must be non-negative integers, match statuses must be valid).
*   **`news_expectations.py`**: Defines rules for the news data (e.g., URLs must not be null, dates must fall within the current season).

### ↳ `nlp/` (Natural Language Processing)
*   **`sentiment.py`**: Queries unscored news articles from the `silver` layer, passes their content through a Hugging Face Transformer model (`cardiffnlp/twitter-roberta-base-sentiment-latest`), and writes the sentiment labels and confidence scores to a `silver_sentiment_scores` table. Logs runs to MLflow.

### ↳ `ml/` (Machine Learning)
*   **`features.py`**: Takes the raw historical match data and engineers advanced features like Elo ratings, rolling points, goal differences, and win streaks for model training.
*   **`train.py`**: Trains the XGBoost predictive model on the historical features, evaluates its accuracy (handling class imbalances like draws), and logs the model artifacts and metrics to MLflow.
*   **`predict.py`**: Loads the trained model and applies it to the *current live season data*. It runs 1,000 Monte Carlo simulations of the remaining fixtures to calculate the percentage chance each team has of winning the title, writing results to `gold_title_predictions`.

### ↳ `api/` (Serving Layer)
Uses `FastAPI` to expose the processed data in the `gold` schema for the dashboard to consume.
*   **`main.py`**: The entry point for the FastAPI application, registering the routers.
*   **`database.py`**: Handles creating database sessions for API requests.
*   **`routers/`**: Contains the individual API endpoints for fetching team performance, team sentiment, matchweek summaries, and title predictions.

### ↳ `dagster_assets/` (Orchestration)
Uses `Dagster` to wire all the above components together into automated pipelines.
*   **`definitions.py`**: The main entry point for Dagster, registering all assets, jobs, and resources.
*   **`jobs.py`**: Defines two distinct jobs: `matchweek_pipeline` (automated end-to-end run for live data) and `model_training_job` (manual run for historical training).
*   **`resources.py`**: Defines shared resources (like the Postgres connection and API keys) injected into Dagster assets.
*   **`assets/`**: Contains the Python functions wrapped in `@asset` decorators for `ingestion.py`, `quality.py`, `transformations.py` (dbt), `nlp_scoring.py`, and `model_scoring.py`.

---

## 📁 `dbt_project/` (Data Transformation Layer)
Uses `dbt` (Data Build Tool) to transform raw data into analytics-ready models using SQL.
*   **`dbt_project.yml`**: The main dbt configuration file.
*   **`models/sources.yml`**: Maps the raw tables in the Postgres `bronze` schema so dbt can reference them.
*   **`models/silver/`**: SQL files that clean, deduplicate, and standardize the raw match and news data (e.g., standardizing different spellings of team names).
*   **`models/gold/`**: SQL files that build the final dimensional model (`dim_team`, `dim_matchweek`) and the main fact table (`fact_team_sentiment_performance`) combining match stats with NLP sentiment scores.

---

## 📁 `streamlit_app/` (Data Visualization)
Uses `Streamlit` to build the interactive user dashboard.
*   **`app.py`**: The main entry point for the dashboard. It fetches the latest title predictions from the FastAPI backend and displays the active Title Race probabilities.
*   **`utils.py`**: Helper functions for making HTTP requests to the FastAPI backend.
*   **`pages/`**: Contains sub-pages for the dashboard, such as an Overview page (showing league-wide scatter plots of sentiment vs. performance) and a Team Detail page (showing specific trends for individual clubs).
