"""Chart builders and report-table parsing used by the dashboard (no network, no Streamlit runtime)."""

import pandas as pd
import pytest

pytest.importorskip("plotly")
pytest.importorskip("streamlit")

from streamlit_app import charts, theme  # noqa: E402
from streamlit_app.utils import parse_md_tables, to_numeric  # noqa: E402


def _preds(n=8):
    teams = [f"Team {i}" for i in range(n)]
    return pd.DataFrame(
        {
            "team": teams,
            "win_probability": [0.5, 0.3, 0.1, 0.05, 0.03, 0.01, 0.005, 0.005][:n],
            "top4_probability": [0.9 - 0.1 * i for i in range(n)],
            "relegation_probability": [0.01 * i for i in range(n)],
            "avg_final_points": [80 - 5 * i for i in range(n)],
            "points_p10": [72 - 5 * i for i in range(n)],
            "points_p90": [88 - 5 * i for i in range(n)],
            "avg_final_rank": list(range(1, n + 1)),
        }
    )


def _standings(articles):
    return pd.DataFrame(
        {
            "team": [f"Team {i}" for i in range(len(articles))],
            "tla": [f"T{i}" for i in range(len(articles))],
            "avg_sentiment": [0.2, -0.1, 0.05, -0.3, 0.1, 0.0][: len(articles)],
            "article_count": articles,
            "points": [3, 0, 1, 3, 0, 1][: len(articles)],
            "result": ["W", "L", "D", "W", "L", "D"][: len(articles)],
            "goals_for": [2, 0, 1, 1, 0, 1][: len(articles)],
            "goals_against": [0, 1, 1, 0, 2, 1][: len(articles)],
        }
    )


def test_team_colors_follow_title_rank_and_the_rest_are_grey():
    colors = theme.team_colors([f"T{i}" for i in range(10)])
    assert len(colors) == 5 and colors["T0"] == theme.TEAM_INKS[0]
    assert theme.color_for("T9", colors) == theme.OTHER
    reserved = {theme.POS, theme.NEG, theme.WIN, theme.LOSS}
    assert not reserved & set(theme.TEAM_INKS)  # blue, green and red never double as a club


def test_title_race_charts_build():
    preds, colors = _preds(), theme.team_colors(_preds()["team"].tolist())
    assert len(charts.title_donut(preds, colors).data) == 1
    assert len(charts.points_range(preds, colors).data) == 2
    assert len(charts.probability_heatmap(preds).data) == 1


def test_sentiment_bars_leave_out_thin_coverage_instead_of_ranking_it():
    fig = charts.sentiment_bars(_standings([20, 12, 3, 9, 1, 0]))
    shown = list(fig.data[0].y)
    assert sorted(shown) == ["Team 0", "Team 1", "Team 3"]  # only 8+ articles
    assert charts.sentiment_bars(_standings([1, 2, 0, 3, 0, 1])) is None


def test_sentiment_vs_points_needs_enough_covered_clubs():
    assert charts.sentiment_vs_points(_standings([20, 12, 3, 9, 1, 0])) is None  # only 3 clubs covered
    assert charts.sentiment_vs_points(_standings([20, 12, 30, 9, 15, 11])) is not None


def test_coverage_donut_none_when_no_articles():
    colors = theme.team_colors([])
    assert charts.coverage_donut(_standings([0, 0, 0, 0]), colors) is None
    assert charts.coverage_donut(_standings([5, 3, 2, 1]), colors) is not None


def test_coverage_donut_reuses_club_inks_and_folds_the_rest_into_grey():
    colors = theme.team_colors(["Team 1", "Team 0"])  # only these two have inks
    fig = charts.coverage_donut(_standings([5, 3, 2, 1]), colors)
    assert list(fig.data[0].labels) == ["Team 0", "Team 1", "All other clubs"]
    assert list(fig.data[0].marker.colors) == [colors["Team 0"], colors["Team 1"], theme.OTHER]
    assert list(fig.data[0].values) == [5, 3, 3]


def test_sentiment_heatmap_blanks_thin_cells_and_handles_empty():
    summaries = {1: {"standings": _standings([20, 12, 3, 9, 1, 0]).to_dict("records")}}
    fig = charts.sentiment_heatmap(summaries)
    z = fig.data[0].z
    flat = [v for row in z for v in row]
    assert flat.count(None) == 3 and sum(v is not None for v in flat) == 3
    thin = {1: {"standings": _standings([1, 2, 0, 3, 0, 1]).to_dict("records")}}
    assert charts.sentiment_heatmap(thin) is None
    assert charts.sentiment_heatmap({}) is None


def test_odds_history_needs_two_matchweeks():
    one = pd.DataFrame({"matchweek": [5, 5], "team": ["A", "B"], "win_probability": [0.6, 0.4]})
    assert charts.odds_history(one, {}) is None
    two = pd.concat([one, one.assign(matchweek=6)])
    assert charts.odds_history(two, {}) is not None


def test_team_charts_build():
    perf = pd.DataFrame(
        {
            "matchweek": [1, 2, 3], "result": ["W", "D", "L"], "goals_for": [2, 1, 0], "goals_against": [0, 1, 2],
            "points": [3, 1, 0], "goal_difference": [2, 0, -2], "cumulative_points": [3, 4, 4], "cumulative_gd": [2, 2, 0],
        }
    )
    sent = pd.DataFrame({"matchweek": [1, 2, 3], "avg_sentiment_score": [0.1, 0.0, -0.1], "article_count": [20, 15, 9]})
    assert charts.result_donut(perf) is not None
    assert charts.points_line(perf, "#3987e5") is not None
    assert charts.goals_chart(perf) is not None
    assert charts.sentiment_trend(sent, "#3987e5") is not None
    assert charts.sentiment_vs_goal_diff(perf, sent) is not None
    assert charts.sentiment_vs_goal_diff(perf, sent.assign(article_count=[1, 2, 3])) is None  # thin coverage


def test_fixture_row_shows_score_once_played_and_escapes_names():
    base = {"kickoff": "2026-10-10 11:30:00+00:00", "home_team": "A & B", "away_team": "C", "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2}
    upcoming = theme.fixture_row({**base, "played": False})
    played = theme.fixture_row({**base, "played": True, "score_home": 2, "score_away": 1})
    assert "A &amp; B" in upcoming and "fx-mid score" not in upcoming
    assert "2–1" in played and "Sat 10 Oct" in played


def test_prob_rail_hides_labels_on_slivers():
    rail = theme.prob_rail(0.9, 0.08, 0.02)
    assert "90%" in rail and "8%" not in rail and "2%" not in rail


REPORT = """Intro line.

| model | log_loss | accuracy |
|---|---|---|
| prior | 1.0741 | 0.4282 |
| blend | 0.9952 | 0.5241 |

Other text

| season | prior |
|---|---|
| 2020 | 1.0971 |
"""


def test_parse_md_tables_and_numeric_conversion():
    tables = parse_md_tables(REPORT)
    assert len(tables) == 2
    heading, first = tables[0]
    assert heading == "Intro line." and list(first.columns) == ["model", "log_loss", "accuracy"]
    numeric = to_numeric(first, skip=("model",))
    assert numeric["log_loss"].tolist() == [1.0741, 0.9952] and numeric["model"].tolist() == ["prior", "blend"]


def test_focus_helpers_brighten_followed_and_dim_the_rest(monkeypatch):
    monkeypatch.setattr(theme.st, "session_state", {"follow": "Arsenal"})
    assert theme.followed() == "Arsenal"
    assert theme.focus_color("Arsenal", "#3987e5") == theme.lit("#3987e5")
    assert theme.focus_color("Chelsea", "#3987e5").startswith("rgba(")
    monkeypatch.setattr(theme.st, "session_state", {"follow": "— none —"})
    assert theme.followed() is None
    assert theme.focus_color("Chelsea", "#3987e5") == "#3987e5"


def test_a_followed_outsider_burns_porcelain(monkeypatch):
    monkeypatch.setattr(theme.st, "session_state", {"follow": "Team 15"})
    colors = theme.team_colors([f"Team {i}" for i in range(10)])
    assert colors["Team 15"] == theme.PORCELAIN


def test_count_markup_keeps_the_final_value_for_reduced_motion():
    small, large = theme.count(5, " of 38"), theme.count(1901)
    assert 'data-v="5"' in small and "of 38" in small and "--lo:5" in small
    assert 'data-v="1,901"' in large and "--hi:1" in large and "--lo:901" in large


def test_signed_never_prints_negative_zero():
    assert charts._signed(-0.0004) == "0.00"
    assert charts._signed(0.05) == "+0.05" and charts._signed(-0.2) == "-0.20"


def test_dot_plot_does_not_start_bars_at_a_truncated_axis():
    df = pd.DataFrame({"model": ["prior", "blend"], "log_loss": [1.0741, 0.9952]})
    fig = charts.dot_plot(df, "model", "log_loss")
    assert fig.data[1].mode == "markers+text" and len(fig.data[1].x) == 2
    assert "axis starts at" in fig.layout.xaxis.title.text  # the truncation is disclosed


def test_crest_uses_the_feed_image_or_a_monogram_and_dims_when_another_club_is_followed(monkeypatch):
    monkeypatch.setattr(theme.st, "session_state", {})
    theme.set_clubs({"Arsenal": {"tla": "ARS", "short": "Arsenal", "crest": "https://crests.example/57.png"},
                     "Hull City": {"tla": "HUL", "short": "Hull", "crest": ""}})
    assert 'src="https://crests.example/57.png"' in theme.crest("Arsenal", 30) and 'width="30"' in theme.crest("Arsenal", 30)
    mono = theme.crest("Hull City")
    assert "mono" in mono and ">HUL<" in mono
    monkeypatch.setattr(theme.st, "session_state", {"follow": "Arsenal"})
    assert "lit" in theme.crest("Arsenal") and "dim" in theme.crest("Hull City")
    theme.set_clubs({})


def test_fixture_row_shows_both_crests(monkeypatch):
    monkeypatch.setattr(theme.st, "session_state", {})
    theme.set_clubs({"A": {"tla": "AAA", "short": "A", "crest": "https://c/a.png"}, "B": {"tla": "BBB", "short": "B", "crest": "https://c/b.png"}})
    row = theme.fixture_row({"kickoff": "2026-10-10 11:30:00+00:00", "home_team": "A", "away_team": "B",
                             "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2, "played": False})
    assert "https://c/a.png" in row and "https://c/b.png" in row
    theme.set_clubs({})


def test_pitch_artwork_is_an_inline_svg_data_uri():
    assert theme.PITCH_URI.startswith("data:image/svg+xml;utf8,") and "circle" in theme.PITCH_URI


def test_pitch_uri_is_safe_inside_a_css_url_string():
    uri = theme.PITCH_URI
    assert '"' not in uri and "#" not in uri and " " not in uri and "\n" not in uri
