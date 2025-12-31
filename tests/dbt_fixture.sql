-- Hand-built league for the dbt integration test (tests/test_dbt_pipeline.py).
-- Four clubs, three matchweeks; MW1 and MW2 are played, MW3 is scheduled.
--
--   MW1  Arsenal 2-0 Chelsea        (2026-08-22 15:00)   Liverpool 1-1 Everton (2026-08-23 15:00)
--   MW2  Chelsea 0-3 Liverpool      (2026-08-30 15:00)   Everton 0-1 Arsenal   (2026-08-30 15:00)
--   MW3  Arsenal v Liverpool        (2026-09-13 15:00)   Chelsea v Everton     (2026-09-13 15:00)

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE bronze.raw_matches (
    id BIGINT, matchday BIGINT, status TEXT, stage TEXT, utc_date TIMESTAMPTZ,
    home_team_id BIGINT, home_team_name TEXT, home_team_short TEXT, home_team_tla TEXT, home_team_crest TEXT,
    away_team_id BIGINT, away_team_name TEXT, away_team_short TEXT, away_team_tla TEXT, away_team_crest TEXT,
    score_winner TEXT, score_home BIGINT, score_away BIGINT, score_home_ht BIGINT, score_away_ht BIGINT,
    season BIGINT, competition_code TEXT, last_updated TEXT, ingested_at TIMESTAMPTZ
);

INSERT INTO bronze.raw_matches
    (id, matchday, status, stage, utc_date, home_team_id, home_team_name, home_team_short, home_team_tla,
     away_team_id, away_team_name, away_team_short, away_team_tla, score_winner, score_home, score_away,
     score_home_ht, score_away_ht, season, competition_code, ingested_at)
VALUES
 (1, 1, 'FINISHED', 'REGULAR_SEASON', '2026-08-22 15:00+00', 57, 'Arsenal FC', 'Arsenal', 'ARS', 61, 'Chelsea FC', 'Chelsea', 'CHE', 'HOME_TEAM', 2, 0, 1, 0, 2026, 'PL', now()),
 (2, 1, 'FINISHED', 'REGULAR_SEASON', '2026-08-23 15:00+00', 64, 'Liverpool FC', 'Liverpool', 'LIV', 62, 'Everton FC', 'Everton', 'EVE', 'DRAW', 1, 1, 0, 0, 2026, 'PL', now()),
 (3, 2, 'FINISHED', 'REGULAR_SEASON', '2026-08-30 15:00+00', 61, 'Chelsea FC', 'Chelsea', 'CHE', 64, 'Liverpool FC', 'Liverpool', 'LIV', 'AWAY_TEAM', 0, 3, 0, 1, 2026, 'PL', now()),
 (4, 2, 'FINISHED', 'REGULAR_SEASON', '2026-08-30 15:00+00', 62, 'Everton FC', 'Everton', 'EVE', 57, 'Arsenal FC', 'Arsenal', 'ARS', 'AWAY_TEAM', 0, 1, 0, 0, 2026, 'PL', now()),
 (5, 3, 'TIMED', 'REGULAR_SEASON', '2026-09-13 15:00+00', 57, 'Arsenal FC', 'Arsenal', 'ARS', 64, 'Liverpool FC', 'Liverpool', 'LIV', NULL, NULL, NULL, NULL, NULL, 2026, 'PL', now()),
 (6, 3, 'TIMED', 'REGULAR_SEASON', '2026-09-13 15:00+00', 61, 'Chelsea FC', 'Chelsea', 'CHE', 62, 'Everton FC', 'Everton', 'EVE', NULL, NULL, NULL, NULL, NULL, 2026, 'PL', now());

CREATE TABLE bronze.raw_news_articles (
    url TEXT, title TEXT, description TEXT, content TEXT, source_name TEXT,
    published_at TEXT, team_query TEXT, ingested_at TEXT
);

INSERT INTO bronze.raw_news_articles (url, title, description, source_name, published_at, team_query, ingested_at) VALUES
 -- preview of a head-to-head match: Arsenal is the subject, Chelsea the opponent
 ('u1', 'Arsenal confident ahead of Chelsea clash', '', 'BBC Sport', '2026-08-20T09:00:00+00:00', 'Arsenal', '2026-09-01T00:00:00+00:00'),
 -- single club, between MW1 and MW2
 ('u2', 'Liverpool injury crisis deepens', 'Slot has few options', 'BBC Sport', '2026-08-25T09:00:00+00:00', 'Liverpool', '2026-09-01T00:00:00+00:00'),
 -- round-up naming three clubs: must not count for anyone
 ('u3', 'Saturday gossip: Arsenal, Chelsea and Liverpool target striker', '', 'BBC Sport', '2026-08-26T09:00:00+00:00', 'Arsenal', '2026-09-01T00:00:00+00:00'),
 -- match report published AFTER the Everton v Arsenal kickoff: must be attributed to MW3, never MW2
 ('u4', 'Arsenal beat Everton with a late goal', '', 'BBC Sport', '2026-08-30T20:00:00+00:00', 'Arsenal', '2026-09-01T00:00:00+00:00'),
 -- names no club: falls back to the club it was searched for (Everton); next match is MW1
 ('u5', 'Weekend preview', 'What to look out for', 'Sky Sports', '2026-08-21T09:00:00+00:00', 'Everton', '2026-09-01T00:00:00+00:00'),
 -- two clubs with no shared next/previous fixture (a transfer story): only the first-named counts
 ('u6', 'Chelsea sign Everton winger', '', 'BBC Sport', '2026-08-24T09:00:00+00:00', 'Chelsea', '2026-09-01T00:00:00+00:00');

CREATE TABLE silver.silver_sentiment_scores (
    article_url TEXT PRIMARY KEY, sentiment_label TEXT NOT NULL, sentiment_score FLOAT NOT NULL,
    model_name TEXT NOT NULL, scored_at TIMESTAMP NOT NULL
);

INSERT INTO silver.silver_sentiment_scores VALUES
 ('u1', 'POSITIVE', 0.9, 'test', now()),
 ('u2', 'NEGATIVE', 0.8, 'test', now()),
 ('u3', 'POSITIVE', 0.7, 'test', now()),
 ('u4', 'POSITIVE', 0.6, 'test', now()),
 ('u5', 'NEUTRAL',  0.5, 'test', now()),
 ('u6', 'POSITIVE', 0.5, 'test', now());
