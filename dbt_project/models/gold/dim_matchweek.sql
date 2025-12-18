/*
    PLanalyst — Gold Layer: dim_matchweek

    Dimension table for matchweeks.
    One row per matchweek with number, date range and completion status,
    derived from all fixtures (finished or not).
*/

{{ config(
    materialized='table',
    schema='gold'
) }}

WITH matchweek_dates AS (
    SELECT
        matchday AS matchweek_number,
        MIN(utc_date::timestamp) AS start_date,
        MAX(utc_date::timestamp) AS end_date,
        COUNT(*) AS total_matches,
        COUNT(*) FILTER (WHERE status = 'FINISHED') AS matches_played
    FROM {{ source('bronze', 'raw_matches') }}
    WHERE matchday IS NOT NULL
    GROUP BY matchday
)

SELECT
    matchweek_number AS matchweek_key,
    matchweek_number,
    start_date,
    end_date,
    total_matches,
    matches_played,
    -- complete once every scheduled fixture in the matchweek is finished
    (matches_played = total_matches) AS is_complete
FROM matchweek_dates
ORDER BY matchweek_number
