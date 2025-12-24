/*
    PLanalyst — Gold Layer: fact_team_sentiment_performance

    Fact table: one row per team per matchweek.
    Combines match results with pre-match news sentiment (see silver_article_teams).

    Columns: team, matchweek, avg_sentiment_score, article_count,
             result (W/D/L), goals_for, goals_against, points.
*/

{{ config(
    materialized='table',
    schema='gold'
) }}

WITH team_match_results AS (
    -- Unpivot matches: one row per team per match (home and away)
    SELECT
        home_team AS team_name,
        matchday AS matchweek_number,
        home_result AS result,
        home_goals AS goals_for,
        away_goals AS goals_against,
        home_points AS points,
        home_gd AS goal_difference
    FROM {{ ref('silver_matches') }}

    UNION ALL

    SELECT
        away_team AS team_name,
        matchday AS matchweek_number,
        away_result AS result,
        away_goals AS goals_for,
        home_goals AS goals_against,
        away_points AS points,
        away_gd AS goal_difference
    FROM {{ ref('silver_matches') }}
),

-- Sentiment per team and matchweek. Each article counts for the team's NEXT fixture at the time
-- it was published (see silver_article_teams), so it is always pre-match for that match.
-- Polarity flips the sign for an opponent named in a head-to-head article and drops
-- round-ups and ambiguous mentions (polarity 0). Only matchweeks that have since been played
-- appear in this fact table, so sentiment for upcoming fixtures waits here until they finish.
sentiment_data AS (
    SELECT
        at.team_name,
        at.next_matchweek AS matchweek_number,
        AVG(at.polarity * CASE
            WHEN ss.sentiment_label = 'POSITIVE' THEN ss.sentiment_score
            WHEN ss.sentiment_label = 'NEGATIVE' THEN -ss.sentiment_score
            ELSE 0
        END) AS avg_sentiment_score,
        COUNT(DISTINCT at.article_url) AS article_count
    FROM {{ ref('silver_article_teams') }} at
    INNER JOIN {{ source('silver', 'silver_sentiment_scores') }} ss
        ON at.article_url = ss.article_url
    WHERE at.polarity <> 0
      AND at.next_matchweek IS NOT NULL
    GROUP BY at.team_name, at.next_matchweek
),

-- Join results with sentiment
combined AS (
    SELECT
        tmr.team_name,
        tmr.matchweek_number,
        tmr.result,
        tmr.goals_for,
        tmr.goals_against,
        tmr.points,
        tmr.goal_difference,
        COALESCE(sd.avg_sentiment_score, 0) AS avg_sentiment_score,
        COALESCE(sd.article_count, 0) AS article_count
    FROM team_match_results tmr
    LEFT JOIN sentiment_data sd
        ON tmr.team_name = sd.team_name
        AND tmr.matchweek_number = sd.matchweek_number
),

-- Add dimension keys
with_keys AS (
    SELECT
        dt.team_key,
        dm.matchweek_key,
        c.team_name,
        c.matchweek_number,
        c.result,
        c.goals_for,
        c.goals_against,
        c.points,
        c.goal_difference,
        c.avg_sentiment_score,
        c.article_count,
        -- Cumulative stats
        SUM(c.points) OVER (
            PARTITION BY c.team_name ORDER BY c.matchweek_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_points,
        SUM(c.goal_difference) OVER (
            PARTITION BY c.team_name ORDER BY c.matchweek_number
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_gd
    FROM combined c
    LEFT JOIN {{ ref('dim_team') }} dt ON c.team_name = dt.team_name
    LEFT JOIN {{ ref('dim_matchweek') }} dm ON c.matchweek_number = dm.matchweek_number
)

SELECT * FROM with_keys
ORDER BY matchweek_number, cumulative_points DESC, cumulative_gd DESC
