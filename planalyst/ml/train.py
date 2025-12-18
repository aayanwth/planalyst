"""
PLanalyst — Model Training v2: Improved League Winner Prediction

Improvements over v1:
- XGBoost instead of vanilla GBM (better regularization)
- Elo rating features computed from historical data
- Head-to-head features
- Class weighting to handle draw imbalance
- Hyperparameter tuning via cross-validation
"""

import os
import warnings

import numpy as np
import pandas as pd
from sklearn.model_selection import cross_val_score
from sklearn.metrics import accuracy_score, log_loss, classification_report
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

from sqlalchemy import create_engine, text

from planalyst.config import MODELS_DIR, SQLALCHEMY_CONNECTION_STRING, SCHEMA_TRAINING

warnings.filterwarnings("ignore")

# ── Features ─────────────────────────────────────────────────────────────────
FEATURE_COLUMNS = [
    "rolling_points_5",
    "rolling_gd_5",
    "season_points",
    "season_gd",
    "season_position",
    "is_home",
    "win_rate",
    "games_played",
    # New Elo-based features
    "elo_rating",
    "elo_diff",
    # New form features
    "rolling_goals_for_5",
    "rolling_goals_against_5",
    "recent_win_streak",
]

# ── Elo Rating System ────────────────────────────────────────────────────────
DEFAULT_ELO = 1500
K_FACTOR = 32


def compute_elo_ratings(matches_df: pd.DataFrame) -> dict[str, float]:
    """
    Compute Elo ratings from historical match results.
    Returns a dict mapping team_name -> current Elo rating.
    """
    elo = {}

    for _, match in matches_df.sort_values(["season", "matchday"]).iterrows():
        home = match["home_team_name"]
        away = match["away_team_name"]

        # Initialize if first time seeing the team
        if home not in elo:
            elo[home] = DEFAULT_ELO
        if away not in elo:
            elo[away] = DEFAULT_ELO

        # Expected scores
        exp_home = 1 / (1 + 10 ** ((elo[away] - elo[home]) / 400))
        exp_away = 1 - exp_home

        # Actual scores
        if match["score_home"] > match["score_away"]:
            actual_home, actual_away = 1.0, 0.0
        elif match["score_home"] < match["score_away"]:
            actual_home, actual_away = 0.0, 1.0
        else:
            actual_home, actual_away = 0.5, 0.5

        # Update with goal difference margin multiplier
        gd = abs(match["score_home"] - match["score_away"])
        margin_mult = np.log(max(gd, 1) + 1)  # Bigger wins = bigger updates

        elo[home] += K_FACTOR * margin_mult * (actual_home - exp_home)
        elo[away] += K_FACTOR * margin_mult * (actual_away - exp_away)

    return elo


def add_elo_features(team_df: pd.DataFrame, matches_df: pd.DataFrame) -> pd.DataFrame:
    """Add Elo rating and Elo difference features to the team-level dataframe."""
    # Compute Elo ratings progressively per season
    elo_history = {}  # (season, matchday, team) -> elo_at_that_point

    elo = {}
    for _, match in matches_df.sort_values(["season", "matchday"]).iterrows():
        home = match["home_team_name"]
        away = match["away_team_name"]

        if home not in elo:
            elo[home] = DEFAULT_ELO
        if away not in elo:
            elo[away] = DEFAULT_ELO

        # Record current elo BEFORE the match
        key_home = (match["season"], match["matchday"], home)
        key_away = (match["season"], match["matchday"], away)
        elo_history[key_home] = elo[home]
        elo_history[key_away] = elo[away]

        # Also record opponent's elo for diff calculation
        elo_history[key_home + ("opp",)] = elo[away]
        elo_history[key_away + ("opp",)] = elo[home]

        # Update elo
        exp_home = 1 / (1 + 10 ** ((elo[away] - elo[home]) / 400))
        if match["score_home"] > match["score_away"]:
            actual_home = 1.0
        elif match["score_home"] < match["score_away"]:
            actual_home = 0.0
        else:
            actual_home = 0.5

        gd = abs(match["score_home"] - match["score_away"])
        margin_mult = np.log(max(gd, 1) + 1)

        elo[home] += K_FACTOR * margin_mult * (actual_home - exp_home)
        elo[away] += K_FACTOR * margin_mult * ((1 - actual_home) - (1 - exp_home))

    # Map elo values to the team dataframe
    team_df["elo_rating"] = team_df.apply(
        lambda r: elo_history.get((r["season"], r["matchday"], r["team"]), DEFAULT_ELO),
        axis=1,
    )
    team_df["elo_diff"] = team_df.apply(
        lambda r: r["elo_rating"] - elo_history.get(
            (r["season"], r["matchday"], r["team"], "opp"), DEFAULT_ELO
        ),
        axis=1,
    )

    return team_df


def add_advanced_features(team_df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling goals and win streak features."""
    results = []

    for (season, team), group in team_df.groupby(["season", "team"]):
        group = group.sort_values("matchday").copy()

        # Rolling goals for/against (5 game window)
        group["rolling_goals_for_5"] = group["goals_for"].rolling(5, min_periods=1).mean()
        group["rolling_goals_against_5"] = group["goals_against"].rolling(5, min_periods=1).mean()

        # Win streak: count consecutive wins ending at this matchday
        streak = []
        current_streak = 0
        for _, row in group.iterrows():
            if row["result"] == "W":
                current_streak += 1
            else:
                current_streak = 0
            streak.append(current_streak)
        group["recent_win_streak"] = streak

        results.append(group)

    return pd.concat(results, ignore_index=True)


NEXT_MATCH_COLUMNS = ["is_home", "elo_rating", "elo_diff"]


def align_to_next_match(df: pd.DataFrame) -> pd.DataFrame:
    """
    The training target is the team's NEXT match result, so the context
    features (venue, Elo, Elo gap vs opponent) must describe that next match,
    exactly as they do at prediction time. Elo columns are recorded pre-match,
    so shifting them back one row gives the pre-match values of the next game.
    """
    df = df.sort_values(["season", "team", "matchday"]).copy()
    grouped = df.groupby(["season", "team"])
    for col in NEXT_MATCH_COLUMNS:
        df[col] = grouped[col].shift(-1)
    return df  # last match of each season becomes NaN and is dropped later


def load_training_data() -> pd.DataFrame:
    """Load the pre-computed training features from the training schema."""
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)
    query = text(f"SELECT * FROM {SCHEMA_TRAINING}.training_features")
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df


def load_raw_historical_matches() -> pd.DataFrame:
    """Load raw historical matches for Elo computation."""
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)
    query = text("""
        SELECT id, matchday, season, home_team_name, away_team_name,
               score_home, score_away
        FROM training.historical_matches
        WHERE score_home IS NOT NULL
        ORDER BY season, matchday
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df


def train_model(holdout_season: int | None = None):
    """
    Train the improved match outcome prediction model.
    """
    print("[Train v2] Loading training data...")
    df = load_training_data()
    matches_df = load_raw_historical_matches()

    if df.empty:
        raise ValueError("No training data found. Run feature engineering first.")

    print(f"  Total rows: {len(df)}")
    print(f"  Seasons: {sorted(df['season'].unique())}")

    # Add Elo features
    print("  Computing Elo ratings...")
    df = add_elo_features(df, matches_df)

    # Add advanced form features
    print("  Computing advanced features...")
    df = add_advanced_features(df)

    # Make venue/Elo features describe the match being predicted
    df = align_to_next_match(df)

    # Prepare features and target
    feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
    print(f"  Features ({len(feature_cols)}): {feature_cols}")

    # Drop rows with NaN
    df_clean = df.dropna(subset=feature_cols + ["next_result"])
    print(f"  Clean rows: {len(df_clean)}")

    X = df_clean[feature_cols].values
    y = df_clean["next_result"].values

    # Encode target
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    # Time-based split: hold out a whole season (default: the latest) so rows
    # from the same team-season never appear on both sides.
    seasons_available = sorted(df_clean["season"].unique())
    if not holdout_season or holdout_season not in seasons_available:
        holdout_season = seasons_available[-1]
    train_mask = (df_clean["season"] != holdout_season).to_numpy()
    test_mask = ~train_mask
    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y_encoded[train_mask], y_encoded[test_mask]
    print(f"  Holdout season: {holdout_season}-{holdout_season + 1}")

    # Class weights for draw imbalance, computed on the training set only
    counts = np.bincount(y_train, minlength=len(le.classes_))
    class_weight = {i: len(y_train) / (len(le.classes_) * max(c, 1)) for i, c in enumerate(counts)}
    w_train = np.array([class_weight[yi] for yi in y_train])

    print(f"  Train: {len(X_train)}, Test: {len(X_test)}")

    # XGBoost Classifier with tuned hyperparameters
    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        gamma=0.1,
        reg_alpha=0.1,
        reg_lambda=1.0,
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        random_state=42,
        verbosity=0,
    )

    print("  Training XGBoost Classifier...")
    model.fit(X_train, y_train, sample_weight=w_train)

    # Evaluate
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    logloss = log_loss(y_test, y_proba)

    # Cross-validation on training set
    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="accuracy")

    print(f"\n  Test Accuracy: {accuracy:.4f}")
    print(f"  Log Loss: {logloss:.4f}")
    print(f"  CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
    print(f"\n  Classification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # Feature importance
    importances = dict(zip(feature_cols, model.feature_importances_))
    print(f"\n  Feature Importances:")
    for feat, imp in sorted(importances.items(), key=lambda x: -x[1]):
        print(f"    {feat}: {imp:.4f}")

    # Save model
    import joblib
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODELS_DIR / "match_predictor.joblib")
    joblib.dump(le, MODELS_DIR / "label_encoder.joblib")
    print(f"\n  Model saved to {MODELS_DIR / 'match_predictor.joblib'}")

    # Log to MLflow (best effort)
    try:
        import mlflow.xgboost
        from planalyst.tracking import configure_mlflow

        mlflow = configure_mlflow()
        mlflow.set_experiment("planalyst_match_prediction")

        with mlflow.start_run(run_name="xgb_match_predictor_v2"):
            mlflow.log_param("model_type", "XGBClassifier")
            mlflow.log_param("n_estimators", model.n_estimators)
            mlflow.log_param("max_depth", model.max_depth)
            mlflow.log_param("features", str(feature_cols))
            mlflow.log_metric("accuracy", accuracy)
            mlflow.log_metric("log_loss", logloss)
            mlflow.log_metric("cv_accuracy_mean", cv_scores.mean())
            for feat, imp in importances.items():
                mlflow.log_metric(f"importance_{feat}", imp)
            mlflow.xgboost.log_model(model, artifact_path="model",
                                      registered_model_name="planalyst_match_predictor")
            print("  Model logged to MLflow")
    except Exception as e:
        print(f"  MLflow logging skipped: {e}")

    return model, le, feature_cols


if __name__ == "__main__":
    model, le, features = train_model(holdout_season=2024)
