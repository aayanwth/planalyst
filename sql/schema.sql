-- =============================================================================
-- EPL Analytics Data Warehouse — Star Schema DDL
-- Database: epl_analytics_db
-- MySQL 8.0+
-- =============================================================================

CREATE DATABASE IF NOT EXISTS epl_analytics_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE epl_analytics_db;

-- =============================================================================
-- DIMENSION TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- dim_dates: Calendar dimension for time-based analysis
-- Pre-populated for the full 2026/27 season (Aug 2026 – Jun 2027)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_dates (
    date_id         INT             NOT NULL AUTO_INCREMENT,
    full_date       DATE            NOT NULL,
    day_of_week     VARCHAR(10)     NOT NULL,
    day_num         TINYINT         NOT NULL,
    month_num       TINYINT         NOT NULL,
    month_name      VARCHAR(10)     NOT NULL,
    year            SMALLINT        NOT NULL,
    season          VARCHAR(10)     NOT NULL DEFAULT '2026/27',
    is_weekend      TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (date_id),
    UNIQUE KEY uq_full_date (full_date)
) ENGINE=InnoDB;

-- -----------------------------------------------------------------------------
-- dim_teams: Team dimension from FPL /bootstrap-static/ → teams[]
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_teams (
    team_id                 INT             NOT NULL,
    team_code               INT             NOT NULL,
    team_name               VARCHAR(50)     NOT NULL,
    short_name              VARCHAR(5)      NOT NULL,
    strength_overall_home   TINYINT         NULL,
    strength_overall_away   TINYINT         NULL,
    strength_attack_home    TINYINT         NULL,
    strength_attack_away    TINYINT         NULL,
    strength_defence_home   TINYINT         NULL,
    strength_defence_away   TINYINT         NULL,
    pulse_id                INT             NULL,
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id),
    INDEX idx_short_name (short_name)
) ENGINE=InnoDB;

-- -----------------------------------------------------------------------------
-- dim_players: Player dimension from FPL /bootstrap-static/ → elements[]
-- now_cost stored as INT (tenths of £M, e.g. 60 = £6.0M)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_players (
    player_id           INT             NOT NULL,
    player_code         INT             NOT NULL,
    first_name          VARCHAR(50)     NOT NULL,
    second_name         VARCHAR(50)     NOT NULL,
    web_name            VARCHAR(50)     NOT NULL,
    team_id             INT             NOT NULL,
    element_type        TINYINT         NOT NULL COMMENT '1=GKP,2=DEF,3=MID,4=FWD',
    position            VARCHAR(3)      NOT NULL DEFAULT '',
    now_cost            INT             NOT NULL DEFAULT 0,
    status              VARCHAR(5)      NOT NULL DEFAULT 'a',
    chance_of_playing    TINYINT        NULL,
    news                VARCHAR(255)    NULL,
    total_points        INT             NOT NULL DEFAULT 0,
    points_per_game     DECIMAL(5,2)    NOT NULL DEFAULT 0.00,
    selected_by_percent DECIMAL(5,2)    NOT NULL DEFAULT 0.00,
    form                DECIMAL(5,2)    NOT NULL DEFAULT 0.00,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (player_id),
    INDEX idx_player_team (team_id),
    INDEX idx_player_element_type (element_type),
    INDEX idx_player_cost (now_cost),
    CONSTRAINT fk_player_team
        FOREIGN KEY (team_id) REFERENCES dim_teams(team_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB;

-- -----------------------------------------------------------------------------
-- dim_fixtures: Fixture dimension from FPL /fixtures/
-- One row per scheduled match
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dim_fixtures (
    fixture_id          INT             NOT NULL,
    fixture_code        INT             NOT NULL,
    gameweek            TINYINT         NULL COMMENT 'NULL if unscheduled',
    kickoff_time        DATETIME        NULL COMMENT 'NULL if postponed',
    team_h              INT             NOT NULL,
    team_a              INT             NOT NULL,
    team_h_score        TINYINT         NULL,
    team_a_score        TINYINT         NULL,
    team_h_difficulty   TINYINT         NULL,
    team_a_difficulty   TINYINT         NULL,
    finished            TINYINT(1)      NOT NULL DEFAULT 0,
    date_id             INT             NULL,
    updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                        ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (fixture_id),
    INDEX idx_fixture_gw (gameweek),
    INDEX idx_fixture_kickoff (kickoff_time),
    INDEX idx_fixture_team_h (team_h),
    INDEX idx_fixture_team_a (team_a),
    INDEX idx_fixture_date (date_id),
    CONSTRAINT fk_fixture_team_h
        FOREIGN KEY (team_h) REFERENCES dim_teams(team_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_fixture_team_a
        FOREIGN KEY (team_a) REFERENCES dim_teams(team_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_fixture_date
        FOREIGN KEY (date_id) REFERENCES dim_dates(date_id)
        ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB;


-- =============================================================================
-- FACT TABLES
-- =============================================================================

-- -----------------------------------------------------------------------------
-- fact_match_performances: Team-level match stats (Option A — aggregated from
-- player-level data). Two rows per fixture (one per team).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_match_performances (
    performance_id      INT             NOT NULL AUTO_INCREMENT,
    fixture_id          INT             NOT NULL,
    team_id             INT             NOT NULL,
    gameweek            TINYINT         NOT NULL,
    date_id             INT             NULL,
    is_home             TINYINT(1)      NOT NULL DEFAULT 0,
    -- Aggregated stats (summed from player-level data)
    goals_scored        TINYINT         NOT NULL DEFAULT 0,
    goals_conceded      TINYINT         NOT NULL DEFAULT 0,
    shots               SMALLINT        NOT NULL DEFAULT 0 COMMENT 'Approx from threat metric',
    shots_on_target     SMALLINT        NOT NULL DEFAULT 0,
    xg                  DECIMAL(5,2)    NOT NULL DEFAULT 0.00,
    xg_conceded         DECIMAL(5,2)    NOT NULL DEFAULT 0.00,
    xg_overperformance  DECIMAL(5,2)    GENERATED ALWAYS AS (goals_scored - xg) STORED,
    total_bps           SMALLINT        NOT NULL DEFAULT 0,
    clean_sheet         TINYINT(1)      NOT NULL DEFAULT 0,
    result              CHAR(1)         NULL COMMENT 'W/D/L',
    PRIMARY KEY (performance_id),
    UNIQUE KEY uq_fixture_team (fixture_id, team_id),
    INDEX idx_perf_team (team_id),
    INDEX idx_perf_gw (gameweek),
    INDEX idx_perf_date (date_id),
    CONSTRAINT fk_perf_fixture
        FOREIGN KEY (fixture_id) REFERENCES dim_fixtures(fixture_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_perf_team
        FOREIGN KEY (team_id) REFERENCES dim_teams(team_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_perf_date
        FOREIGN KEY (date_id) REFERENCES dim_dates(date_id)
        ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB;

-- -----------------------------------------------------------------------------
-- fact_player_gameweeks: Player-level per-gameweek performance stats
-- from FPL /event/{gw}/live/ endpoint
-- Composite PK for natural idempotent upserts
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_player_gameweeks (
    player_id               INT             NOT NULL,
    gameweek                TINYINT         NOT NULL,
    fixture_id              INT             NULL,
    minutes                 SMALLINT        NOT NULL DEFAULT 0,
    goals_scored            TINYINT         NOT NULL DEFAULT 0,
    assists                 TINYINT         NOT NULL DEFAULT 0,
    clean_sheets            TINYINT         NOT NULL DEFAULT 0,
    goals_conceded          TINYINT         NOT NULL DEFAULT 0,
    own_goals               TINYINT         NOT NULL DEFAULT 0,
    penalties_saved         TINYINT         NOT NULL DEFAULT 0,
    penalties_missed        TINYINT         NOT NULL DEFAULT 0,
    yellow_cards            TINYINT         NOT NULL DEFAULT 0,
    red_cards               TINYINT         NOT NULL DEFAULT 0,
    saves                   TINYINT         NOT NULL DEFAULT 0,
    bonus                   TINYINT         NOT NULL DEFAULT 0,
    bps                     SMALLINT        NOT NULL DEFAULT 0,
    influence               DECIMAL(6,2)    NOT NULL DEFAULT 0.00,
    creativity              DECIMAL(6,2)    NOT NULL DEFAULT 0.00,
    threat                  DECIMAL(6,2)    NOT NULL DEFAULT 0.00,
    ict_index               DECIMAL(6,2)    NOT NULL DEFAULT 0.00,
    starts                  TINYINT         NOT NULL DEFAULT 0,
    expected_goals          DECIMAL(5,2)    NULL DEFAULT 0.00,
    expected_assists        DECIMAL(5,2)    NULL DEFAULT 0.00,
    expected_goal_involvements DECIMAL(5,2) NULL DEFAULT 0.00,
    expected_goals_conceded DECIMAL(5,2)    NULL DEFAULT 0.00,
    total_points            SMALLINT        NOT NULL DEFAULT 0,
    updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                            ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (player_id, gameweek),
    INDEX idx_pgw_player (player_id),
    INDEX idx_pgw_gw (gameweek),
    INDEX idx_pgw_fixture (fixture_id),
    CONSTRAINT fk_pgw_player
        FOREIGN KEY (player_id) REFERENCES dim_players(player_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_pgw_fixture
        FOREIGN KEY (fixture_id) REFERENCES dim_fixtures(fixture_id)
        ON UPDATE CASCADE ON DELETE SET NULL
) ENGINE=InnoDB;


-- =============================================================================
-- POPULATE dim_dates: Aug 1, 2026 through Jun 30, 2027
-- Uses a recursive CTE (MySQL 8.0+)
-- =============================================================================
INSERT IGNORE INTO dim_dates (full_date, day_of_week, day_num, month_num, month_name, year, season, is_weekend)
WITH RECURSIVE date_series AS (
    SELECT DATE('2026-08-01') AS dt
    UNION ALL
    SELECT dt + INTERVAL 1 DAY
    FROM date_series
    WHERE dt < '2027-06-30'
)
SELECT
    dt,
    DAYNAME(dt),
    DAY(dt),
    MONTH(dt),
    MONTHNAME(dt),
    YEAR(dt),
    '2026/27',
    CASE WHEN DAYOFWEEK(dt) IN (1, 7) THEN 1 ELSE 0 END
FROM date_series;
