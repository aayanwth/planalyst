/*
    PLanalyst — Gold Layer: dim_team

    Dimension table for all PL teams.
    One row per team with canonical name and metadata.
    Built from ALL fixtures (not just finished matches) so teams that have
    not played yet still appear.
*/

{{ config(
    materialized='table',
    schema='gold'
) }}

WITH fixtures AS (
    SELECT * FROM {{ source('bronze', 'raw_matches') }}
),

all_teams AS (
    SELECT
        {{ map_team_name('home_team_name') }} AS team_name,
        home_team_id AS team_id,
        home_team_short AS short_name,
        home_team_tla AS tla,
        home_team_crest AS crest_url,
        ingested_at
    FROM fixtures
    UNION ALL
    SELECT
        {{ map_team_name('away_team_name') }},
        away_team_id,
        away_team_short,
        away_team_tla,
        away_team_crest,
        ingested_at
    FROM fixtures
),

latest AS (
    -- One row per team; latest ingestion wins if metadata changed
    SELECT DISTINCT ON (team_name)
        team_name, team_id, short_name, tla, crest_url
    FROM all_teams
    ORDER BY team_name, ingested_at DESC
)

SELECT
    ROW_NUMBER() OVER (ORDER BY team_name) AS team_key,
    team_id,
    team_name,
    short_name,
    tla,
    crest_url
FROM latest
