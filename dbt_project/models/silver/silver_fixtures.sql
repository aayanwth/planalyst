/*
    PLanalyst — Silver Layer: silver_fixtures

    EVERY fixture of the live season (played or not) with canonical team names and an explicit
    UTC kickoff time. silver_matches only holds finished matches, so it cannot answer "which
    match is this team's NEXT one", which is what news attribution needs.
*/

{{ config(
    materialized='view',
    schema='silver'
) }}

SELECT DISTINCT ON (id)
    id,
    matchday,
    status,
    (utc_date AT TIME ZONE 'UTC') AS match_date,
    {{ map_team_name('home_team_name') }} AS home_team,
    {{ map_team_name('away_team_name') }} AS away_team,
    season
FROM {{ source('bronze', 'raw_matches') }}
WHERE matchday IS NOT NULL
  AND utc_date IS NOT NULL
ORDER BY id, ingested_at DESC
