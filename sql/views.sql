-- =============================================================================
-- EPL Analytics — Analytical Views for Power BI
-- Database: epl_analytics_db
-- Requires: All Star Schema tables populated
-- =============================================================================

USE epl_analytics_db;

-- =============================================================================
-- VIEW 1: vw_team_tactical_form
-- 
-- Purpose: Team-level rolling 5-match moving averages for tactical analysis.
-- Calculates rolling possession proxy (BPS), shots, xG, and
-- over/underperformance metrics (Actual Goals - xG).
--
-- Consumed by: Power BI Page 1 (Team Tactical & Form)
-- =============================================================================

DROP VIEW IF EXISTS vw_team_tactical_form;

CREATE VIEW vw_team_tactical_form AS
SELECT
    perf.performance_id,
    perf.fixture_id,
    perf.team_id,
    t.team_name,
    t.short_name,
    perf.gameweek,
    perf.is_home,
    perf.goals_scored,
    perf.goals_conceded,
    perf.shots,
    perf.shots_on_target,
    perf.xg,
    perf.xg_conceded,
    perf.xg_overperformance,
    perf.total_bps,
    perf.clean_sheet,
    perf.result,
    d.full_date                                         AS match_date,
    d.day_of_week,

    -- ---------------------------------------------------------------
    -- Rolling 5-match moving averages (window functions)
    -- ---------------------------------------------------------------
    ROUND(
        AVG(perf.xg) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 2
    )                                                   AS rolling_5m_avg_xg,

    ROUND(
        AVG(perf.xg_conceded) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 2
    )                                                   AS rolling_5m_avg_xg_conceded,

    ROUND(
        AVG(perf.goals_scored) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 2
    )                                                   AS rolling_5m_avg_goals,

    ROUND(
        AVG(perf.shots) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 1
    )                                                   AS rolling_5m_avg_shots,

    ROUND(
        AVG(perf.shots_on_target) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 1
    )                                                   AS rolling_5m_avg_sot,

    ROUND(
        AVG(perf.total_bps) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 0
    )                                                   AS rolling_5m_avg_bps,

    -- Over/underperformance: rolling avg actual goals - rolling avg xG
    ROUND(
        AVG(perf.goals_scored) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        )
        -
        AVG(perf.xg) OVER (
            PARTITION BY perf.team_id
            ORDER BY perf.gameweek
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ), 2
    )                                                   AS rolling_5m_xg_overperf,

    -- Cumulative season totals
    SUM(perf.goals_scored) OVER (
        PARTITION BY perf.team_id
        ORDER BY perf.gameweek
    )                                                   AS cumulative_goals,

    SUM(perf.xg) OVER (
        PARTITION BY perf.team_id
        ORDER BY perf.gameweek
    )                                                   AS cumulative_xg,

    -- Home vs Away split indicator for bar chart
    CASE WHEN perf.is_home = 1 THEN 'Home' ELSE 'Away' END AS venue

FROM fact_match_performances perf
JOIN dim_teams t          ON perf.team_id = t.team_id
LEFT JOIN dim_dates d     ON perf.date_id = d.date_id
ORDER BY perf.team_id, perf.gameweek;


-- =============================================================================
-- VIEW 2: vw_player_value_matrix
--
-- Purpose: Player-level value analysis with xGI/90, cost efficiency,
-- and upcoming fixture difficulty ratings.
--
-- Consumed by: Power BI Page 2 (Player Recruitment & Value)
-- =============================================================================

DROP VIEW IF EXISTS vw_player_value_matrix;

CREATE VIEW vw_player_value_matrix AS
SELECT
    p.player_id,
    p.web_name,
    p.first_name,
    p.second_name,
    p.position,
    p.element_type,
    p.team_id,
    t.team_name,
    t.short_name                                        AS team_short,
    p.now_cost,
    ROUND(p.now_cost / 10.0, 1)                         AS cost_millions,
    p.status,
    p.total_points,
    p.points_per_game,
    p.form,
    p.selected_by_percent,

    -- ---------------------------------------------------------------
    -- Aggregated season stats (from fact_player_gameweeks)
    -- ---------------------------------------------------------------
    COALESCE(agg.total_minutes, 0)                      AS total_minutes,
    COALESCE(agg.total_goals, 0)                        AS total_goals,
    COALESCE(agg.total_assists, 0)                      AS total_assists,
    COALESCE(agg.total_xg, 0.00)                        AS total_xg,
    COALESCE(agg.total_xa, 0.00)                        AS total_xa,
    COALESCE(agg.total_xgi, 0.00)                       AS total_xgi,
    COALESCE(agg.total_bonus, 0)                        AS total_bonus,
    COALESCE(agg.appearances, 0)                        AS appearances,
    COALESCE(agg.starts_count, 0)                       AS starts_count,

    -- ---------------------------------------------------------------
    -- Per-90 metrics (guard against divide-by-zero)
    -- ---------------------------------------------------------------
    CASE
        WHEN COALESCE(agg.total_minutes, 0) >= 90 THEN
            ROUND(COALESCE(agg.total_xgi, 0) / (agg.total_minutes / 90.0), 2)
        ELSE NULL
    END                                                 AS xgi_per_90,

    CASE
        WHEN COALESCE(agg.total_minutes, 0) >= 90 THEN
            ROUND(COALESCE(agg.total_xg, 0) / (agg.total_minutes / 90.0), 2)
        ELSE NULL
    END                                                 AS xg_per_90,

    CASE
        WHEN COALESCE(agg.total_minutes, 0) >= 90 THEN
            ROUND(COALESCE(agg.total_xa, 0) / (agg.total_minutes / 90.0), 2)
        ELSE NULL
    END                                                 AS xa_per_90,

    -- ---------------------------------------------------------------
    -- Cost efficiency: total_points / cost in millions
    -- ---------------------------------------------------------------
    CASE
        WHEN p.now_cost > 0 THEN
            ROUND(p.total_points / (p.now_cost / 10.0), 2)
        ELSE NULL
    END                                                 AS cost_efficiency,

    -- ---------------------------------------------------------------
    -- Upcoming Fixture Difficulty Rating (next 5 fixtures)
    -- Subquery calculates average FDR for the team's next 5 matches
    -- ---------------------------------------------------------------
    upcoming_fdr.avg_fdr                                AS upcoming_5_avg_fdr,
    upcoming_fdr.fixture_list                           AS upcoming_5_fixtures

FROM dim_players p
JOIN dim_teams t ON p.team_id = t.team_id

-- Aggregated stats subquery
LEFT JOIN (
    SELECT
        player_id,
        SUM(minutes)                                    AS total_minutes,
        SUM(goals_scored)                               AS total_goals,
        SUM(assists)                                    AS total_assists,
        SUM(COALESCE(expected_goals, 0))                AS total_xg,
        SUM(COALESCE(expected_assists, 0))              AS total_xa,
        SUM(COALESCE(expected_goal_involvements, 0))    AS total_xgi,
        SUM(bonus)                                      AS total_bonus,
        COUNT(CASE WHEN minutes > 0 THEN 1 END)        AS appearances,
        SUM(starts)                                     AS starts_count
    FROM fact_player_gameweeks
    GROUP BY player_id
) agg ON p.player_id = agg.player_id

-- Upcoming FDR subquery: average difficulty of next 5 unplayed fixtures
LEFT JOIN (
    SELECT
        sub.team_id,
        ROUND(AVG(sub.difficulty), 2)                   AS avg_fdr,
        GROUP_CONCAT(
            sub.opponent_short ORDER BY sub.gameweek SEPARATOR ', '
        )                                               AS fixture_list
    FROM (
        SELECT
            CASE
                WHEN f.team_h = ranked.team_id THEN f.team_h
                ELSE f.team_a
            END                                         AS team_id,
            ranked.difficulty,
            ranked.gameweek,
            ranked.opponent_short
        FROM (
            -- Home fixtures
            SELECT
                f.team_h                                AS team_id,
                f.team_h_difficulty                     AS difficulty,
                f.gameweek,
                ta.short_name                           AS opponent_short,
                f.fixture_id,
                ROW_NUMBER() OVER (
                    PARTITION BY f.team_h
                    ORDER BY f.gameweek
                )                                       AS rn
            FROM dim_fixtures f
            JOIN dim_teams ta ON f.team_a = ta.team_id
            WHERE f.finished = 0 AND f.gameweek IS NOT NULL

            UNION ALL

            -- Away fixtures
            SELECT
                f.team_a                                AS team_id,
                f.team_a_difficulty                     AS difficulty,
                f.gameweek,
                th.short_name                           AS opponent_short,
                f.fixture_id,
                ROW_NUMBER() OVER (
                    PARTITION BY f.team_a
                    ORDER BY f.gameweek
                )                                       AS rn
            FROM dim_fixtures f
            JOIN dim_teams th ON f.team_h = th.team_id
            WHERE f.finished = 0 AND f.gameweek IS NOT NULL
        ) ranked
        -- Re-join to get full fixture for the CASE
        JOIN dim_fixtures f ON ranked.fixture_id = f.fixture_id
        WHERE ranked.rn <= 5
    ) sub
    GROUP BY sub.team_id
) upcoming_fdr ON p.team_id = upcoming_fdr.team_id;
