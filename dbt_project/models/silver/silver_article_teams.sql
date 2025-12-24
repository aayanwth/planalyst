/*
    PLanalyst — Silver Layer: silver_article_teams

    Which team(s) each article is about, how its sentiment applies to each, and which match it
    is attributed to. One row per (article, team).

    Teams: every club whose name or alias (seed team_aliases) appears as a whole word in the
    headline or description. If no club is named, the club the article was searched for.

    Attribution: each team's NEXT fixture, i.e. the earliest fixture kicking off at or after
    publication. An article is therefore always pre-match for the match it is attributed to; one
    published during or after a match is attributed to the following match, never to the match
    it reports on.

    Polarity (how the article's sentiment counts for this team):
      1 team named       -> +1
      2 teams, they face each other (next or previous fixture is shared: a preview or a match
         report) -> the first-named team (the headline subject) +1, the other -1
      2 teams, no shared fixture -> first-named +1, the other 0 (excluded)
      3+ teams (round-ups)       -> 0 for everyone (excluded)
    "Subject first" is a heuristic for English headlines ("Arsenal beat Spurs"); it can be checked
    against human labels with `python -m planalyst.nlp.evaluate`.
*/

{{ config(
    materialized='view',
    schema='silver'
) }}

WITH articles AS (
    SELECT
        article_url,
        published_at,
        team_name AS query_team,
        lower(coalesce(title, '') || ' ' || coalesce(description, '')) AS txt
    FROM {{ ref('silver_news_articles') }}
),

aliases AS (
    SELECT DISTINCT lower(alias) AS alias, canonical_name
    FROM {{ ref('team_aliases') }}
),

text_mentions AS (
    SELECT
        a.article_url,
        al.canonical_name AS team_name,
        MIN(strpos(a.txt, al.alias)) AS first_pos
    FROM articles a
    JOIN aliases al
      ON a.txt ~ ('\m' || al.alias || '\M')  -- whole-word match; aliases are plain words (tested)
    GROUP BY a.article_url, al.canonical_name
),

-- Fall back to the searched-for club only when the text names no club at all.
fallback_mentions AS (
    SELECT a.article_url, a.query_team AS team_name, 100000 AS first_pos
    FROM articles a
    WHERE NOT EXISTS (SELECT 1 FROM text_mentions tm WHERE tm.article_url = a.article_url)
),

mentions AS (
    SELECT * FROM text_mentions
    UNION ALL
    SELECT * FROM fallback_mentions
),

with_fixtures AS (
    SELECT
        m.article_url,
        m.team_name,
        m.first_pos,
        (
            SELECT f.id
            FROM {{ ref('silver_fixtures') }} f
            WHERE (f.home_team = m.team_name OR f.away_team = m.team_name)
              AND f.match_date >= a.published_at
            ORDER BY f.match_date
            LIMIT 1
        ) AS next_fixture_id,
        (
            SELECT f.id
            FROM {{ ref('silver_fixtures') }} f
            WHERE (f.home_team = m.team_name OR f.away_team = m.team_name)
              AND f.match_date < a.published_at
            ORDER BY f.match_date DESC
            LIMIT 1
        ) AS previous_fixture_id
    FROM mentions m
    JOIN articles a USING (article_url)
),

scored AS (
    SELECT
        *,
        COUNT(*) OVER w AS n_teams,
        ROW_NUMBER() OVER (PARTITION BY article_url ORDER BY first_pos, team_name) AS mention_rank,
        COALESCE(
            (COUNT(next_fixture_id) OVER w = 2
                AND MIN(next_fixture_id) OVER w = MAX(next_fixture_id) OVER w)
            OR (COUNT(previous_fixture_id) OVER w = 2
                AND MIN(previous_fixture_id) OVER w = MAX(previous_fixture_id) OVER w),
            FALSE
        ) AS shared_fixture
    FROM with_fixtures
    WINDOW w AS (PARTITION BY article_url)
)

SELECT
    s.article_url,
    s.team_name,
    s.n_teams AS teams_mentioned,
    (s.n_teams = 2 AND s.shared_fixture) AS is_head_to_head,
    CASE
        WHEN s.n_teams = 1 THEN 1
        WHEN s.n_teams = 2 AND s.shared_fixture THEN CASE WHEN s.mention_rank = 1 THEN 1 ELSE -1 END
        WHEN s.n_teams = 2 THEN CASE WHEN s.mention_rank = 1 THEN 1 ELSE 0 END
        ELSE 0
    END AS polarity,
    s.next_fixture_id,
    f.matchday AS next_matchweek,
    f.match_date AS next_kickoff
FROM scored s
LEFT JOIN {{ ref('silver_fixtures') }} f ON f.id = s.next_fixture_id
