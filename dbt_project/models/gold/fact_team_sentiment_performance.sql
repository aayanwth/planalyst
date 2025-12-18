/*
    PLanalyst — Gold Layer: fact_team_sentiment_performance

    Fact table: one row per team per matchweek.
    Combines match results with news sentiment scores.

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

-- Attribute each scored article to the team's nearest played matchweek
-- (article date on or before the match; otherwise the latest played MW).
team_matchweeks AS (
    SELECT home_team AS team_name, matchday AS matchweek_number, match_date
    FROM {{ ref('silver_matches') }}
    UNION ALL
    SELECT away_team, matchday, match_date
    FROM {{ ref('silver_matches') }}
),

articles_with_matchweek AS (
    SELECT
        sna.article_url,
        sna.team_name,
        COALESCE(
            (
                SELECT MIN(tm.matchweek_number)
                FROM team_matchweeks tm
                WHERE tm.team_name = sna.team_name
                  AND tm.match_date >= sna.published_at
            ),
            (
                SELECT MAX(tm.matchweek_number)
                FROM team_matchweeks tm
                WHERE tm.team_name = sna.team_name
            )
        ) AS matchweek_number,
        ss.sentiment_label,
        ss.sentiment_score
    FROM {{ ref('silver_news_articles') }} sna
    INNER JOIN {{ source('silver', 'silver_sentiment_scores') }} ss
        ON sna.article_url = ss.article_url
),

sentiment_data AS (
    SELECT
        team_name,
        matchweek_number,
        AVG(CASE
            WHEN sentiment_label = 'POSITIVE' THEN sentiment_score
            WHEN sentiment_label = 'NEGATIVE' THEN -sentiment_score
            ELSE 0
        END) AS avg_sentiment_score,
        COUNT(article_url) AS article_count
    FROM articles_with_matchweek
    WHERE matchweek_number IS NOT NULL
    GROUP BY team_name, matchweek_number
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
