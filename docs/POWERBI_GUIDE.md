# Power BI Desktop — Setup & DAX Guide

> **EPL Analytics Data Warehouse → Power BI Integration**
>
> This guide walks you through connecting Power BI Desktop to the local MySQL
> data warehouse, importing the correct views/tables, writing DAX measures,
> and building the 2-page report.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [MySQL Connection Setup](#2-mysql-connection-setup)
3. [Data Model & Imports](#3-data-model--imports)
4. [DAX Measures](#4-dax-measures)
5. [Page 1 — Team Tactical & Form](#5-page-1--team-tactical--form)
6. [Page 2 — Player Recruitment & Value](#6-page-2--player-recruitment--value)
7. [Refresh & Maintenance](#7-refresh--maintenance)

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Power BI Desktop | Latest (free) | [Download](https://powerbi.microsoft.com/desktop/) |
| MySQL Server | 8.0+ | Running on `127.0.0.1:3306` |
| MySQL ODBC Connector | 8.0+ | Required for Power BI ↔ MySQL |
| EPL Analytics DB | Populated | Run `schema.sql`, `views.sql`, and the ETL pipeline first |

### Install MySQL ODBC Connector

1. Download the **MySQL Connector/ODBC 8.0** from:
   https://dev.mysql.com/downloads/connector/odbc/
2. Install the **64-bit** version (matching Power BI Desktop).
3. Restart Power BI Desktop after installation.

> [!IMPORTANT]
> Power BI requires the **MySQL ODBC driver**, not just `mysql-connector-python`.
> Without it, the "MySQL database" connector will not appear.

---

## 2. MySQL Connection Setup

### Step-by-step Connection

1. Open **Power BI Desktop** → **Home** → **Get Data** → **More...**
2. Search for **MySQL database** → Click **Connect**.
3. Enter connection details:

   | Field | Value |
   |---|---|
   | Server | `127.0.0.1:3306` |
   | Database | `epl_analytics_db` |

4. Select **Import** mode (recommended for this dataset size).
5. Enter MySQL credentials (same as your `.env` file):
   - Username: `root` (or your DB_USER)
   - Password: your `DB_PASSWORD`
6. Click **OK** → Navigator window opens.

### Import vs DirectQuery

| Mode | Recommendation | Why |
|---|---|---|
| **Import** | ✅ Recommended | Dataset is small (<100K rows). Faster visuals, DAX works fully. |
| DirectQuery | ❌ Not recommended | Adds query latency, some DAX functions unsupported. |

---

## 3. Data Model & Imports

### Tables/Views to Import

Select these in the Navigator window:

| Source | Type | Purpose |
|---|---|---|
| `vw_team_tactical_form` | View | Pre-calculated rolling averages, match results |
| `vw_player_value_matrix` | View | Player stats, per-90 metrics, cost efficiency, FDR |
| `dim_teams` | Table | Team dimension (for slicers) |
| `dim_fixtures` | Table | Fixture schedule (for date context) |
| `dim_dates` | Table | Calendar dimension (for time intelligence) |
| `fact_player_gameweeks` | Table | Granular player-GW stats (for custom DAX) |

> [!TIP]
> The two views (`vw_team_tactical_form` and `vw_player_value_matrix`) contain
> pre-joined and pre-calculated columns. Use them as the primary data sources
> for visuals. Fall back to fact tables only for custom aggregations.

### Relationship Model

After import, verify (or create) these relationships in **Model View**:

```
dim_teams.team_id ──────── 1:* ──── vw_team_tactical_form.team_id
dim_teams.team_id ──────── 1:* ──── vw_player_value_matrix.team_id
dim_dates.date_id ──────── 1:* ──── vw_team_tactical_form.date_id (if available)
dim_fixtures.fixture_id ── 1:* ──── fact_player_gameweeks.fixture_id
```

Power BI will auto-detect most relationships. Check the **Model View** diagram
to verify no broken or duplicate relationships.

---

## 4. DAX Measures

Create a dedicated **Measures Table** for organization:
**Modeling** → **New Table** → enter `Measures = {BLANK()}`.

Then add each measure below via **New Measure**.

---

### 4.1 Rolling 5-Match Expected Goals (xG) Average

```dax
Rolling 5M Avg xG =
VAR _CurrentGW = MAX('vw_team_tactical_form'[gameweek])
VAR _CurrentTeam = MAX('vw_team_tactical_form'[team_id])
VAR _Last5 =
    TOPN(
        5,
        FILTER(
            ALL('vw_team_tactical_form'),
            'vw_team_tactical_form'[team_id] = _CurrentTeam
            && 'vw_team_tactical_form'[gameweek] <= _CurrentGW
        ),
        'vw_team_tactical_form'[gameweek], DESC
    )
RETURN
    AVERAGEX(_Last5, 'vw_team_tactical_form'[xg])
```

> [!NOTE]
> The view already has `rolling_5m_avg_xg` as a pre-calculated column.
> Use this DAX measure only if you need dynamic filtering (e.g., user selects
> a specific gameweek range). Otherwise, use the view column directly.

---

### 4.2 Expected Goal Involvement (xGI) per 90 Minutes

```dax
xGI per 90 =
VAR _TotalMinutes = SUM('fact_player_gameweeks'[minutes])
VAR _TotalXGI =
    SUM('fact_player_gameweeks'[expected_goals])
    + SUM('fact_player_gameweeks'[expected_assists])
RETURN
    IF(
        _TotalMinutes >= 90,
        DIVIDE(_TotalXGI, _TotalMinutes / 90, BLANK()),
        BLANK()
    )
```

> [!TIP]
> The minimum 90-minute threshold prevents inflated per-90 stats for players
> with very few minutes. Adjust threshold to 180 or 270 for stricter filtering.

---

### 4.3 Fixture Congestion Flag (3 Games in 7 Days)

```dax
Fixture Congestion =
VAR _CurrentDate = MAX('dim_fixtures'[kickoff_time])
VAR _CurrentTeam = MAX('vw_team_tactical_form'[team_id])
VAR _7DayWindow =
    COUNTROWS(
        FILTER(
            ALL('dim_fixtures'),
            (
                'dim_fixtures'[team_h] = _CurrentTeam
                || 'dim_fixtures'[team_a] = _CurrentTeam
            )
            && 'dim_fixtures'[kickoff_time] >= _CurrentDate - 7
            && 'dim_fixtures'[kickoff_time] <= _CurrentDate
            && 'dim_fixtures'[finished] = 1
        )
    )
RETURN
    IF(_7DayWindow >= 3, "⚠️ Congested", "Normal")
```

---

### 4.4 Cost Efficiency (Points per £M)

```dax
Cost Efficiency =
VAR _TotalPoints = SUM('vw_player_value_matrix'[total_points])
VAR _CostM = MAX('vw_player_value_matrix'[cost_millions])
RETURN
    IF(
        _CostM > 0,
        DIVIDE(_TotalPoints, _CostM, BLANK()),
        BLANK()
    )
```

---

### 4.5 xG Over/Underperformance

```dax
xG Overperformance =
VAR _Goals = SUM('vw_team_tactical_form'[goals_scored])
VAR _xG = SUM('vw_team_tactical_form'[xg])
RETURN
    _Goals - _xG
```

---

### 4.6 Budget Player Flag (< £6M)

```dax
Is Budget Player =
IF(MAX('vw_player_value_matrix'[cost_millions]) < 6, "Budget", "Premium")
```

---

## 5. Page 1 — Team Tactical & Form

### Page Layout Blueprint

```
┌─────────────────────────────────────────────────────────────┐
│  TEAM SLICER (dropdown)              GAMEWEEK RANGE SLICER  │
├──────────────────────────┬──────────────────────────────────┤
│                          │                                  │
│   SCATTER PLOT            │   ROLLING FORM LINE CHART        │
│   xG vs Actual Goals     │   5-Match Moving Averages        │
│                          │                                  │
│   X: xg                 │   X-Axis: gameweek               │
│   Y: goals_scored        │   Lines:                         │
│   Size: shots            │     - rolling_5m_avg_xg          │
│   Color: team_name       │     - rolling_5m_avg_goals       │
│   Reference: Y = X line  │     - rolling_5m_avg_xg_conceded │
│                          │                                  │
├──────────────────────────┴──────────────────────────────────┤
│                                                             │
│   HOME vs AWAY EFFICIENCY BAR CHART                         │
│                                                             │
│   X-Axis: team_name                                         │
│   Y-Axis: AVG of xg                                         │
│   Legend: venue (Home / Away)                               │
│   Clustered Bar Chart, sorted by total xG descending        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│   KPI CARDS ROW                                             │
│   [Avg xG] [Avg Goals] [xG Overperf] [Total Shots]         │
└─────────────────────────────────────────────────────────────┘
```

---

### 5.1 Scatter Plot: xG vs Actual Goals

| Setting | Value |
|---|---|
| Visual type | Scatter chart |
| X-axis | `vw_team_tactical_form[xg]` |
| Y-axis | `vw_team_tactical_form[goals_scored]` |
| Size | `vw_team_tactical_form[shots]` |
| Legend | `vw_team_tactical_form[team_name]` |
| Details | `vw_team_tactical_form[gameweek]` |

**Add reference line**: Analytics pane → **Y = X** trend line, or:
- Add a constant line at slope = 1 (Y-axis = X-axis reference).
- Points **above** the line = overperforming xG.
- Points **below** the line = underperforming xG.

---

### 5.2 Rolling Form Line Chart

| Setting | Value |
|---|---|
| Visual type | Line chart |
| X-axis | `gameweek` |
| Values (lines) | `rolling_5m_avg_xg`, `rolling_5m_avg_goals`, `rolling_5m_avg_xg_conceded` |
| Legend | Automatic (one line per metric) |
| Filter | Use team slicer to focus on one team at a time |

**Formatting tips:**
- Use **dashed line** for `rolling_5m_avg_xg_conceded` (defensive metric).
- Add **data labels** on hover.
- Set Y-axis minimum to 0.

---

### 5.3 Home vs Away Efficiency Bar Chart

| Setting | Value |
|---|---|
| Visual type | Clustered bar chart |
| X-axis | `team_name` |
| Y-axis | Average of `xg` |
| Legend | `venue` column ("Home" / "Away") |
| Sort | Total xG descending |

**Insight**: Teams with significantly higher Home xG than Away xG have a
strong home advantage — relevant for fixture-based predictions.

---

## 6. Page 2 — Player Recruitment & Value

### Page Layout Blueprint

```
┌─────────────────────────────────────────────────────────────┐
│  POSITION SLICER         TEAM SLICER       COST SLIDER      │
├──────────────────────────┬──────────────────────────────────┤
│                          │                                  │
│   QUADRANT SCATTER       │   FDR HEATMAP MATRIX             │
│   Cost vs xGI/90         │   Upcoming 5-Fixture Difficulty  │
│                          │                                  │
│   X: cost_millions       │   Rows: team_name                │
│   Y: xgi_per_90          │   Values: upcoming_5_avg_fdr     │
│   Size: total_points     │   Color: conditional formatting  │
│   Label: web_name        │     1-2: Green (easy)            │
│   Quadrant lines:        │     3: Yellow (medium)           │
│     X = 6.0 (budget)     │     4-5: Red (hard)              │
│     Y = 0.4 (threshold)  │                                  │
│                          │                                  │
├──────────────────────────┴──────────────────────────────────┤
│                                                             │
│   TARGET PLAYERS TABLE (filtered: cost_millions < 6)        │
│                                                             │
│   Columns: web_name, position, team_short, cost_millions,   │
│            total_points, xgi_per_90, cost_efficiency,        │
│            form, upcoming_5_avg_fdr                          │
│                                                             │
│   Sorted by: cost_efficiency DESC                           │
│   Conditional formatting: xgi_per_90 (data bars)            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### 6.1 Quadrant Analysis Scatter Plot

| Setting | Value |
|---|---|
| Visual type | Scatter chart |
| X-axis | `vw_player_value_matrix[cost_millions]` |
| Y-axis | `vw_player_value_matrix[xgi_per_90]` (or DAX `xGI per 90`) |
| Size | `vw_player_value_matrix[total_points]` |
| Legend | `vw_player_value_matrix[position]` |
| Details | `vw_player_value_matrix[web_name]` |

**Quadrant reference lines** (add via Analytics pane):

| Line | Value | Meaning |
|---|---|---|
| Vertical (X-axis) | `6.0` | Budget threshold (£6M) |
| Horizontal (Y-axis) | `0.40` | xGI/90 performance threshold |

**Quadrant interpretation:**

| Quadrant | Location | Label |
|---|---|---|
| Top-Left | Low cost, High xGI/90 | ⭐ **Hidden Gems** |
| Top-Right | High cost, High xGI/90 | 💰 Premium Performers |
| Bottom-Left | Low cost, Low xGI/90 | ⚠️ Bench Fodder |
| Bottom-Right | High cost, Low xGI/90 | 🚫 Overpriced |

---

### 6.2 FDR Heatmap Matrix

| Setting | Value |
|---|---|
| Visual type | Matrix |
| Rows | `team_name` |
| Columns | _(none — single value)_ |
| Values | `upcoming_5_avg_fdr` |

**Conditional formatting** (Format pane → Cell elements → Background color):

| FDR Range | Color | Hex |
|---|---|---|
| 1.0 – 2.0 | Dark Green | `#1B7A1B` |
| 2.0 – 2.5 | Light Green | `#6BCB6B` |
| 2.5 – 3.0 | Yellow | `#FFD700` |
| 3.0 – 3.5 | Orange | `#FF8C00` |
| 3.5 – 5.0 | Red | `#DC143C` |

**Alternative — expanded heatmap**: If you want per-fixture FDR instead of
an average, use the `upcoming_5_fixtures` string column from the view and split
it into a cross-tab using Power Query.

---

### 6.3 Target Players Table (Budget Picks)

| Setting | Value |
|---|---|
| Visual type | Table |
| Source | `vw_player_value_matrix` |
| Page-level filter | `cost_millions < 6` |

**Columns to include** (in order):

| Column | Format | Notes |
|---|---|---|
| `web_name` | Text | Player name |
| `position` | Text | GKP / DEF / MID / FWD |
| `team_short` | Text | Team abbreviation |
| `cost_millions` | Number, 1 decimal | Price in £M |
| `total_points` | Integer | Season total |
| `xgi_per_90` | Number, 2 decimals | Add **data bars** |
| `cost_efficiency` | Number, 2 decimals | Points per £M |
| `form` | Number, 1 decimal | Recent form rating |
| `upcoming_5_avg_fdr` | Number, 2 decimals | Conditional color |

**Sort**: `cost_efficiency` descending (best value first).

**Conditional formatting**:
- `xgi_per_90`: Data bars (green gradient)
- `upcoming_5_avg_fdr`: Background color (green-to-red scale, same as heatmap)
- `form`: Icon set (↑ for > 5.0, → for 2.0-5.0, ↓ for < 2.0)

---

## 7. Refresh & Maintenance

### Manual Refresh

After running the ETL pipeline with new gameweek data:

1. Open the `.pbix` file in Power BI Desktop.
2. Click **Home** → **Refresh**.
3. All imported tables/views will reload from MySQL.

### Scheduled Refresh (Optional)

For automated refresh, publish to Power BI Service and configure:

1. **Publish** → Select a workspace.
2. **Dataset settings** → **Gateway connection** → Configure an
   [On-premises data gateway](https://learn.microsoft.com/power-bi/connect-data/service-gateway-onprem)
   pointing to your local MySQL.
3. Set refresh schedule (e.g., daily at 6 AM after ETL runs).

> [!WARNING]
> Scheduled refresh requires **Power BI Pro** or **Premium** license and an
> on-premises data gateway for local MySQL connections.

### Post-Refresh Checklist

- [ ] Verify latest gameweek data appears in visuals
- [ ] Check rolling averages update correctly on Page 1
- [ ] Confirm new fixtures appear in FDR heatmap on Page 2
- [ ] Spot-check player cost changes reflect updated `now_cost`
