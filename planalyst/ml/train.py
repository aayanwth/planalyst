"""
PLanalyst — Model Training v2: Improved League Winner Prediction

Improvements over v1:
- XGBoost instead of vanilla GBM (better regularization)
- Elo rating features computed from historical data
- Head-to-head features
- Class weighting to handle draw imbalance
- Hyperparameter tuning via cross-validation
"""

import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, log_loss
from sklearn.model_selection import GroupKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sqlalchemy import create_engine, text
from xgboost import XGBClassifier

from planalyst.config import MODELS_DIR, SCHEMA_TRAINING, SQLALCHEMY_CONNECTION_STRING
from planalyst.ml.elo import DEFAULT_ELO, EloParams, pre_match_long, run_elo

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

# ── Elo ratings (implementation lives in planalyst.ml.elo) ───────────────────

def compute_elo_ratings(
    matches_df: pd.DataFrame, params: EloParams | None = None
) -> dict[str, float]:
    """Current Elo rating per team after replaying `matches_df`."""
    return run_elo(matches_df, params)[0]


def add_elo_features(
    team_df: pd.DataFrame, matches_df: pd.DataFrame, params: EloParams | None = None
) -> pd.DataFrame:
    """
    Add `elo_rating` (the team's rating BEFORE the match) and `elo_diff` (own minus opponent)
    to the team-level frame, keyed on (season, matchday, team).
    """
    _, pre = run_elo(matches_df, params)
    long = pre_match_long(pre).drop_duplicates(["season", "matchday", "team"])
    out = team_df.drop(columns=["elo_rating", "elo_diff"], errors="ignore").merge(
        long, on=["season", "matchday", "team"], how="left"
    )
    out["elo_rating"] = out["elo_rating"].fillna(DEFAULT_ELO)
    out["elo_diff"] = (out["elo_rating"] - out["opp_elo"].fillna(DEFAULT_ELO)).astype(float)
    return out.drop(columns=["opp_elo"])


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


def prepare_training_frame(df: pd.DataFrame, matches_df: pd.DataFrame) -> pd.DataFrame:
    """Pure step: add Elo + form features and align context to the next match."""
    df = add_elo_features(df, matches_df)
    df = add_advanced_features(df)
    return align_to_next_match(df)


# Chosen on a validation window (test = 2018-19, train = earlier seasons) that is disjoint
# from the 2020-26 walk-forward evaluation in docs/model_evaluation.md; `python -m
# planalyst.ml.tune` reproduces the comparison. The previous config (depth 6, 300 trees,
# class-weighted) overfit: 1.034 validation log loss vs 0.947 here.
MODEL_PARAMS = {
    "n_estimators": 200,
    "max_depth": 2,
    "learning_rate": 0.03,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 30,
    "reg_lambda": 5.0,
    "objective": "multi:softprob",
    "num_class": 3,
    "eval_metric": "mlogloss",
    "random_state": 42,
    "verbosity": 0,
}


def make_model(**overrides) -> XGBClassifier:
    """The production XGBoost configuration (optionally overridden, for tuning)."""
    return XGBClassifier(**{**MODEL_PARAMS, **overrides})


def fit_model(X_train: np.ndarray, y_train: np.ndarray, sample_weight=None, **overrides):
    """
    Fit on the natural class distribution. Inverse-frequency class weights were tried and
    made probabilities worse (they inflate P(draw)), and the title simulator needs
    calibrated probabilities more than it needs balanced accuracy.
    """
    model = make_model(**overrides)
    model.fit(X_train, y_train, sample_weight=sample_weight)
    return model


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

    # Elo + form features, aligned so context describes the match being predicted
    print("  Computing Elo and form features...")
    df = prepare_training_frame(df, matches_df)

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

    # Time-based split: evaluate on one whole season using only EARLIER seasons for training,
    # so neither same-season rows nor future seasons leak into the reported metrics.
    seasons_available = sorted(df_clean["season"].unique())
    if not holdout_season or holdout_season not in seasons_available:
        holdout_season = seasons_available[-1]
    train_mask = (df_clean["season"] < holdout_season).to_numpy()
    test_mask = (df_clean["season"] == holdout_season).to_numpy()
    if not train_mask.any():
        raise ValueError(f"No seasons before {holdout_season} to train on.")
    X_train, X_test = X[train_mask], X[test_mask]
    y_train, y_test = y_encoded[train_mask], y_encoded[test_mask]
    print(f"  Holdout season: {holdout_season}-{holdout_season + 1}")

    print(f"  Train: {len(X_train)}, Test: {len(X_test)}")

    print("  Training XGBoost Classifier...")
    model = fit_model(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)

    accuracy = accuracy_score(y_test, y_pred)
    logloss = log_loss(y_test, y_proba)

    # Cross-validation on the training set, grouped by season: each match appears twice
    # (once per team), so random folds would leak the same match across train and validation.
    train_seasons = df_clean["season"].to_numpy()[train_mask]
    cv = GroupKFold(n_splits=min(5, len(np.unique(train_seasons))))
    cv_scores = cross_val_score(
        make_model(), X_train, y_train, cv=cv, groups=train_seasons, scoring="accuracy"
    )

    print(f"\n  Test Accuracy: {accuracy:.4f}")
    print(f"  Log Loss: {logloss:.4f}")
    print(f"  CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
    print("\n  Classification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # Feature importance
    importances = dict(zip(feature_cols, model.feature_importances_))
    print("\n  Feature Importances:")
    for feat, imp in sorted(importances.items(), key=lambda x: -x[1]):
        print(f"    {feat}: {imp:.4f}")

    # Metrics above come from the train-before-holdout model. The model that gets saved and
    # served is refit on every available season, which is what predicts live fixtures.
    model = fit_model(X, y_encoded)

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
    model, le, features = train_model()
