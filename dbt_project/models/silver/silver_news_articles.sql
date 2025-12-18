/*
    PLanalyst — Silver Layer: silver_news_articles

    Cleaned, deduplicated news articles from bronze.raw_news_articles.
    Team names are standardized to match the same canonical names used
    in silver_matches (solving the cross-source join key problem).
*/

{{ config(
    materialized='view',
    schema='silver'
) }}

WITH raw AS (
    SELECT *
    FROM {{ source('bronze', 'raw_news_articles') }}
    WHERE title IS NOT NULL
      AND TRIM(title) != ''
),

deduplicated AS (
    SELECT DISTINCT ON (url)
        url,
        title,
        description,
        content,
        source_name,
        published_at,
        -- Standardize team name to canonical form
        {{ map_team_name('team_query') }} AS team_name,
        team_query AS original_team_query,
        ingested_at
    FROM raw
    ORDER BY url, ingested_at DESC
)

SELECT
    url AS article_url,
    title,
    description,
    content,
    source_name,
    published_at::timestamp AS published_at,
    team_name,
    original_team_query,
    ingested_at
FROM deduplicated
WHERE team_name IS NOT NULL
