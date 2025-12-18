/*
    PLanalyst — Silver Layer: silver_matches

    Cleaned, typed, and deduplicated match data from bronze.raw_matches.
    Team names are standardized to canonical names via the team_name_lookup seed.
    Computes result (W/D/L) and points for both home and away teams.
*/

{{ config(
    materialized='view',
    schema='silver'
) }}

WITH raw AS (
    SELECT *
    FROM {{ source('bronze', 'raw_matches') }}
    WHERE status = 'FINISHED'  -- Only include completed matches
),

deduplicated AS (
    SELECT DISTINCT ON (id)
        id,
        matchday,
        status,
        utc_date::timestamp AS match_date,
        -- Standardize team names
        {{ map_team_name('home_team_name') }} AS home_team,
        {{ map_team_name('away_team_name') }} AS away_team,
        home_team_id,
        away_team_id,
        home_team_short,
        away_team_short,
        home_team_tla,
        away_team_tla,
        home_team_crest,
        away_team_crest,
        -- Scores
        score_home::int AS home_goals,
        score_away::int AS away_goals,
        score_home_ht::int AS home_goals_ht,
        score_away_ht::int AS away_goals_ht,
        score_winner,
        -- Metadata
        season,
        last_updated,
        ingested_at
    FROM raw
    ORDER BY id, ingested_at DESC  -- Latest ingestion wins on dedup
),

with_results AS (
    SELECT
        *,
        -- Home team result
        CASE
            WHEN home_goals > away_goals THEN 'W'
            WHEN home_goals = away_goals THEN 'D'
            ELSE 'L'
        END AS home_result,
        -- Away team result
        CASE
            WHEN away_goals > home_goals THEN 'W'
            WHEN away_goals = home_goals THEN 'D'
            ELSE 'L'
        END AS away_result,
        -- Points
        CASE
            WHEN home_goals > away_goals THEN 3
            WHEN home_goals = away_goals THEN 1
            ELSE 0
        END AS home_points,
        CASE
            WHEN away_goals > home_goals THEN 3
            WHEN away_goals = home_goals THEN 1
            ELSE 0
        END AS away_points,
        -- Goal difference
        home_goals - away_goals AS home_gd,
        away_goals - home_goals AS away_gd
    FROM deduplicated
)

SELECT * FROM with_results
