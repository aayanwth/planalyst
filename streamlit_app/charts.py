"""
PLanalyst — Chart builders.

Every function returns a styled Plotly figure (or None when there is nothing honest to draw).
Forms follow the job of the data: donuts for share of a whole, bars and dots for magnitude,
diverging bars/heatmaps for polarity, ranges for uncertainty, lines for change over time.

The followed club (set in the sidebar) burns brightest on every chart that shows clubs;
the rest of the field recedes.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from streamlit_app import theme
from streamlit_app.theme import (
    BORDER,
    DIVERGING,
    NEG,
    OTHER,
    PORCELAIN,
    POS,
    RESULT_COLORS,
    SERIES,
    SURFACE,
    TEXT,
    TEXT_2,
    TEXT_3,
    dim,
    donut,
    followed,
    lit,
    style_fig,
)

# Fewer articles than this and a team's weekly sentiment is anecdote, not signal.
MIN_ARTICLES = 8

RESULT_SYMBOLS = {"W": "circle", "D": "diamond", "L": "square"}  # result is never colour alone


def _signed(value: float, digits: int = 2) -> str:
    """Signed number that never prints a negative zero."""
    rounded = round(value, digits)
    return f"{0:.{digits}f}" if rounded == 0 else f"{rounded:+.{digits}f}"


# ── Title race ────────────────────────────────────────────────────────────────

def title_donut(preds: pd.DataFrame, colors: dict[str, str], top: int = 5, height: int = 340) -> go.Figure:
    """Share of the title probability: the top teams and everyone else."""
    ranked = preds.sort_values("win_probability", ascending=False)
    head, rest = ranked.head(top), ranked.iloc[top:]
    labels = head["team"].tolist() + (["Rest of the field"] if len(rest) else [])
    values = head["win_probability"].tolist() + ([float(rest["win_probability"].sum())] if len(rest) else [])
    slice_colors = [theme.color_for(t, colors) for t in head["team"]] + ([OTHER] if len(rest) else [])
    leader = ranked.iloc[0]
    return donut(
        labels, values, slice_colors,
        center_text=f"{leader['win_probability']:.0%}", center_sub=str(leader["team"]), height=height,
    )


def _follow_row_outline(fig: go.Figure, ys: list[str], n_cols: int) -> None:
    """Porcelain outline around the followed club's row in a heatmap."""
    follow = followed()
    if follow and follow in ys:
        i = ys.index(follow)
        fig.add_shape(type="rect", x0=-0.5, x1=n_cols - 0.5, y0=i - 0.5, y1=i + 0.5, xref="x", yref="y",
                      line=dict(color=PORCELAIN, width=2), layer="above")


def points_range(preds: pd.DataFrame, colors: dict[str, str], height: int | None = None) -> go.Figure:
    """Expected final points with the 10th–90th percentile range of the simulation."""
    d = preds.sort_values("avg_final_points", ascending=True)
    teams = d["team"].tolist()
    follow = followed()
    base = {t: theme.color_for(t, colors) if t in colors else "#9ec5f4" for t in teams}
    bar_colors = [
        (dim(lit(base[t]), 0.55) if t == follow else (dim(base[t], 0.28) if follow else "rgba(143,168,222,0.45)")) for t in teams
    ]
    dot_colors = [theme.focus_color(t, base[t]) for t in teams]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=teams, x=(d["points_p90"] - d["points_p10"]), base=d["points_p10"], orientation="h",
            marker=dict(color=bar_colors, line=dict(width=0)), width=0.46,
            customdata=d[["points_p10", "points_p90"]].to_numpy(),
            hovertemplate="%{y}<br>Likely range <b>%{customdata[0]:.0f}–%{customdata[1]:.0f}</b> pts<extra></extra>",
            name="10th–90th percentile",
        )
    )
    fig.add_trace(
        go.Scatter(
            y=teams, x=d["avg_final_points"], mode="markers",
            marker=dict(size=[15 if t == follow else 10 for t in teams], color=dot_colors, line=dict(color=SURFACE, width=2)),
            hovertemplate="%{y}<br>Expected <b>%{x:.1f}</b> pts<extra></extra>",
            name="Expected points",
        )
    )
    style_fig(fig, height=height or max(420, 26 * len(teams) + 40), legend=True)
    fig.update_xaxes(title_text="Final points", range=[max(0, d["points_p10"].min() - 4), d["points_p90"].max() + 4])
    fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT_2, size=12))
    fig.update_layout(bargap=0.4)
    return fig


def _annotated_heatmap(z, x, y, colorscale, zmin, zmax, fmt, hover, height, text_threshold, zmid=None, custom=None,
                       follow_outline=True) -> go.Figure:
    fig = go.Figure(
        go.Heatmap(
            z=z, x=x, y=y, colorscale=colorscale, zmin=zmin, zmax=zmax, zmid=zmid,
            xgap=3, ygap=3, showscale=False, hoverongaps=False, customdata=custom, hovertemplate=hover,
        )
    )
    for yi, row in enumerate(z):
        for xi, value in enumerate(row):
            if value is None or pd.isna(value):
                continue
            if zmid is not None:
                bright = abs(value - zmid) / max(abs(zmax - zmid), 1e-9)
            else:
                bright = (value - zmin) / max(zmax - zmin, 1e-9)
            fig.add_annotation(
                x=x[xi], y=y[yi], text=fmt(value), showarrow=False,
                font=dict(size=12, color="#0A1128" if bright > text_threshold else TEXT),
            )
    style_fig(fig, height=height)
    fig.update_xaxes(side="top", showgrid=False, tickfont=dict(color=TEXT_2, size=12))
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(color=TEXT_2, size=12))
    if follow_outline:
        _follow_row_outline(fig, list(y), len(x))
    return fig


SEQUENTIAL = [[0.0, "#12204a"], [0.25, "#1c5cab"], [0.6, "#3987e5"], [1.0, "#9ec5f4"]]


def probability_heatmap(preds: pd.DataFrame) -> go.Figure:
    """Title / top-4 / relegation probability for every team, ordered by expected finish."""
    d = preds.sort_values("avg_final_rank")
    cols = [("win_probability", "Title"), ("top4_probability", "Top 4"), ("relegation_probability", "Relegation")]
    z = [[float(row[c]) if pd.notna(row[c]) else None for c, _ in cols] for _, row in d.iterrows()]
    return _annotated_heatmap(
        z, [n for _, n in cols], d["team"].tolist(), SEQUENTIAL, 0, 1, lambda v: f"{v:.0%}",
        "%{y} · %{x}<br><b>%{z:.1%}</b><extra></extra>", height=max(420, 28 * len(d) + 60), text_threshold=0.55,
    )


def odds_history(history: pd.DataFrame, colors: dict[str, str], top_n: int = 6) -> go.Figure | None:
    """Title probability by matchweek for the current favourites (needs ≥2 stored matchweeks)."""
    if history.empty or history["matchweek"].nunique() < 2:
        return None
    follow = followed()
    latest = history[history["matchweek"] == history["matchweek"].max()]
    favourites = latest.nlargest(top_n, "win_probability")["team"].tolist()
    if follow and follow not in favourites and (history["team"] == follow).any():
        favourites.append(follow)
    fig = go.Figure()
    for team in favourites:
        t = history[history["team"] == team].sort_values("matchweek")
        color = theme.focus_color(team, theme.color_for(team, colors))
        width = 4 if team == follow else 2.5
        if team == follow:  # glow underlay: the chosen line burns
            fig.add_trace(go.Scatter(x=t["matchweek"], y=t["win_probability"], mode="lines", hoverinfo="skip", showlegend=False,
                                     line=dict(color=dim(theme.color_for(team, colors), 0.22), width=14)))
        fig.add_trace(
            go.Scatter(
                x=t["matchweek"], y=t["win_probability"], mode="lines+markers", name=team,
                line=dict(color=color, width=width), marker=dict(size=9 if team == follow else 7, color=color, line=dict(color=SURFACE, width=2)),
                hovertemplate=f"{team}<br>Matchweek %{{x}} · <b>%{{y:.1%}}</b><extra></extra>",
            )
        )
        fig.add_annotation(x=t["matchweek"].iloc[-1], y=t["win_probability"].iloc[-1], text=f"  {team}", showarrow=False,
                           xanchor="left", font=dict(size=11, color=TEXT if team == follow or not follow else TEXT_3))
    style_fig(fig, height=340, legend=False)
    fig.update_yaxes(tickformat=".0%", title_text="Title probability", rangemode="tozero")
    fig.update_xaxes(title_text="Matchweek", dtick=1)
    fig.update_layout(margin=dict(l=8, r=120, t=8, b=8))
    return fig


# ── Matchweek / sentiment ─────────────────────────────────────────────────────

def sentiment_bars(standings: pd.DataFrame, min_articles: int = MIN_ARTICLES, height: int | None = None,
                   colors: dict[str, str] | None = None) -> go.Figure | None:
    """Diverging bars of average sentiment per team; thin-coverage teams are left out, not ranked."""
    d = standings[standings["article_count"] >= min_articles].sort_values("avg_sentiment", ascending=True)
    if d.empty:
        return None
    follow = followed()
    bound = max(0.2, float(d["avg_sentiment"].abs().max()) * 1.3)
    ink_map = colors
    bar_colors = []
    for team, v in zip(d["team"], d["avg_sentiment"]):
        base = POS if v >= 0 else NEG  # polarity is the direction and hue; the followed club overrides with its own ink
        if team == follow:
            bar_colors.append(lit((ink_map or {}).get(team, base)))
        else:
            bar_colors.append(dim(base, 0.35) if follow else base)
    fig = go.Figure(
        go.Bar(
            y=d["team"], x=d["avg_sentiment"], orientation="h",
            marker=dict(color=bar_colors, line=dict(color=[PORCELAIN if t == follow else "rgba(0,0,0,0)" for t in d["team"]], width=2)),
            text=[_signed(v) for v in d["avg_sentiment"]], textposition="outside", cliponaxis=False,
            textfont=dict(color=TEXT_2, size=11),
            customdata=d[["article_count"]].to_numpy(),
            hovertemplate="%{y}<br>Sentiment <b>%{x:+.3f}</b><br>%{customdata[0]} articles<extra></extra>",
        )
    )
    style_fig(fig, height=height or max(260, 28 * len(d) + 40))
    fig.update_xaxes(range=[-bound, bound], title_text="Average sentiment", zeroline=True, zerolinecolor=BORDER, zerolinewidth=1)
    fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT_2, size=12))
    fig.update_layout(bargap=0.32, margin=dict(l=8, r=40, t=8, b=8))
    return fig


def coverage_donut(standings: pd.DataFrame, colors: dict[str, str], top: int = 6, height: int = 340) -> go.Figure | None:
    """How much of the week's coverage was about the title contenders. Each contender wears its one club ink
    (the same as the odds list); every other club is folded into one grey slice, so no colour is reused."""
    d = standings[standings["article_count"] > 0].sort_values("article_count", ascending=False)
    if d.empty:
        return None
    named = d[d["team"].isin(colors)].head(top)
    rest = d[~d["team"].isin(named["team"])]
    labels = named["team"].tolist() + (["All other clubs"] if len(rest) else [])
    values = named["article_count"].tolist() + ([int(rest["article_count"].sum())] if len(rest) else [])
    slice_colors = [colors[t] for t in named["team"]] + ([OTHER] if len(rest) else [])
    total = int(d["article_count"].sum())
    return donut(labels, values, slice_colors, center_text=f"{total:,}", center_sub="articles", height=height)


def sentiment_vs_points(standings: pd.DataFrame, height: int = 560) -> go.Figure | None:
    """Points vs sentiment, only for teams with enough coverage to mean something."""
    d = standings[standings["article_count"] >= MIN_ARTICLES].copy().reset_index(drop=True)
    if len(d) < 4 or d["avg_sentiment"].nunique() < 2:
        return None
    follow = followed()
    d["pts_jitter"] = d["points"] + ((d.index % 7) - 3) * 0.06
    fig = go.Figure()
    for result, label in (("W", "Win"), ("D", "Draw"), ("L", "Loss")):
        r = d[d["result"] == result].sort_values("avg_sentiment")
        if r.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=r["avg_sentiment"], y=r["pts_jitter"], mode="markers+text", name=f"{label} ({result})", text=r["tla"],
                textposition=["top center" if i % 2 == 0 else "bottom center" for i in range(len(r))],
                textfont=dict(size=11, color=TEXT_3),
                marker=dict(
                    symbol=RESULT_SYMBOLS[result], color=RESULT_COLORS[result],
                    size=[(16 if t == follow else 8 + min(a, 60) ** 0.5 * 2) for t, a in zip(r["team"], r["article_count"])],
                    line=dict(color=[PORCELAIN if t == follow else SURFACE for t in r["team"]], width=[3 if t == follow else 2 for t in r["team"]]),
                    opacity=[1.0 if (not follow or t == follow) else 0.4 for t in r["team"]],
                ),
                customdata=r[["team", "goals_for", "goals_against", "article_count"]].to_numpy(),
                hovertemplate="%{customdata[0]} (" + result + " %{customdata[1]}–%{customdata[2]})<br>Sentiment <b>%{x:+.3f}</b><br>%{customdata[3]} articles<extra></extra>",
            )
        )
    style_fig(fig, height=height, legend=True)
    fig.update_xaxes(title_text="Average sentiment", zeroline=True, zerolinecolor=BORDER)
    fig.update_yaxes(title_text="Points this week", tickvals=[0, 1, 3], range=[-0.7, 3.7])
    return fig


def sentiment_heatmap(summaries: dict[int, dict], min_articles: int = MIN_ARTICLES) -> go.Figure | None:
    """Team × matchweek sentiment; cells with thin coverage stay blank."""
    if not summaries:
        return None
    frames = []
    for week, data in summaries.items():
        s = pd.DataFrame(data["standings"])
        s["matchweek"] = week
        frames.append(s[["team", "matchweek", "avg_sentiment", "article_count"]])
    d = pd.concat(frames)
    d.loc[d["article_count"] < min_articles, "avg_sentiment"] = None
    sent = d.pivot(index="team", columns="matchweek", values="avg_sentiment")
    arts = d.pivot(index="team", columns="matchweek", values="article_count")
    if sent.notna().sum().sum() == 0:
        return None
    order = sent.mean(axis=1, skipna=True).sort_values(ascending=False).index
    sent, arts = sent.loc[order], arts.loc[order]
    weeks = [f"MW{w}" for w in sent.columns]
    z = [[None if pd.isna(v) else float(v) for v in row] for row in sent.to_numpy()]
    return _annotated_heatmap(
        z, weeks, list(sent.index), DIVERGING, -0.4, 0.4, _signed,
        "%{y} · %{x}<br>Sentiment <b>%{z:+.3f}</b><br>%{customdata} articles<extra></extra>",
        height=max(420, 28 * len(sent) + 60), text_threshold=0.5, zmid=0.0, custom=arts.to_numpy(),
    )


# ── Team detail ───────────────────────────────────────────────────────────────

def result_donut(perf: pd.DataFrame, height: int = 280) -> go.Figure:
    counts = perf["result"].value_counts()
    order = [("W", "Wins"), ("D", "Draws"), ("L", "Losses")]
    labels = [f"{name} ({key})" for key, name in order if counts.get(key, 0) > 0]
    values = [int(counts[key]) for key, _ in order if counts.get(key, 0) > 0]
    colors = [RESULT_COLORS[key] for key, _ in order if counts.get(key, 0) > 0]
    fig = donut(labels, values, colors, center_text=f"{int(counts.get('W', 0))}-{int(counts.get('D', 0))}-{int(counts.get('L', 0))}",
                center_sub="W-D-L", height=height)
    fig.update_traces(marker=dict(colors=[dim(c, 0.9) for c in colors], line=dict(color=SURFACE, width=2)))
    return fig


def _glow_line(x, y, color: str, name: str, hover: str, marker_fill=None) -> list[go.Scatter]:
    """A line with a soft glow underlay, the transit-line look."""
    return [
        go.Scatter(x=x, y=y, mode="lines", hoverinfo="skip", showlegend=False, line=dict(color=dim(color, 0.18), width=12, shape="spline", smoothing=0.4)),
        go.Scatter(
            x=x, y=y, mode="lines+markers", name=name, line=dict(color=lit(color, 0.2), width=3, shape="spline", smoothing=0.4),
            marker=dict(size=9, color=marker_fill or lit(color, 0.2), line=dict(color=SURFACE, width=2)),
            fill="tozeroy", fillgradient=dict(type="vertical", colorscale=[[0.0, dim(color, 0.0)], [1.0, dim(color, 0.32)]]),
            hovertemplate=hover,
        ),
    ]


def points_line(perf: pd.DataFrame, color: str, height: int = 300) -> go.Figure:
    fig = go.Figure(_glow_line(perf["matchweek"], perf["cumulative_points"], color, "Points", "Matchweek %{x}<br><b>%{y}</b> points<extra></extra>"))
    style_fig(fig, height=height)
    fig.update_xaxes(title_text="Matchweek", dtick=1)
    fig.update_yaxes(title_text="Cumulative points", rangemode="tozero")
    return fig


def goals_chart(perf: pd.DataFrame, color: str = "#9ec5f4", height: int = 300) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=perf["matchweek"], y=perf["goals_for"], name="Scored", marker=dict(color=lit(color, 0.15), line=dict(width=0)),
                         hovertemplate="Matchweek %{x}<br>Scored <b>%{y}</b><extra></extra>"))
    fig.add_trace(go.Bar(x=perf["matchweek"], y=perf["goals_against"], name="Conceded", marker=dict(color="#7F93C0", line=dict(width=0)),
                         hovertemplate="Matchweek %{x}<br>Conceded <b>%{y}</b><extra></extra>"))
    style_fig(fig, height=height, legend=True)
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    fig.update_xaxes(title_text="Matchweek", dtick=1)
    fig.update_yaxes(title_text="Goals", dtick=1)
    return fig


def sentiment_trend(sent: pd.DataFrame, color: str, height: int = 340) -> go.Figure:
    """Sentiment line over matchweeks with article volume underneath (two rows, one x-axis)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.06)
    thin = sent["article_count"] < MIN_ARTICLES
    fig.add_trace(go.Scatter(x=sent["matchweek"], y=sent["avg_sentiment_score"], mode="lines", hoverinfo="skip", showlegend=False,
                             line=dict(color=dim(color, 0.18), width=12)), row=1, col=1)
    fig.add_trace(
        go.Scatter(
            x=sent["matchweek"], y=sent["avg_sentiment_score"], mode="lines+markers", line=dict(color=lit(color, 0.2), width=3),
            marker=dict(size=10, color=[SURFACE if t else lit(color, 0.2) for t in thin], line=dict(color=lit(color, 0.2), width=2)),
            customdata=sent[["article_count"]].to_numpy(),
            hovertemplate="Matchweek %{x}<br>Sentiment <b>%{y:+.3f}</b><br>%{customdata[0]} articles<extra></extra>",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(x=sent["matchweek"], y=sent["article_count"], marker=dict(color=OTHER, line=dict(width=0)),
               hovertemplate="Matchweek %{x}<br><b>%{y}</b> articles<extra></extra>"),
        row=2, col=1,
    )
    style_fig(fig, height=height)
    fig.update_yaxes(title_text="Sentiment", zeroline=True, zerolinecolor=BORDER, row=1, col=1)
    fig.update_yaxes(title_text="Articles", row=2, col=1)
    fig.update_xaxes(dtick=1, title_text="Matchweek", row=2, col=1)
    return fig


def sentiment_vs_goal_diff(perf: pd.DataFrame, sent: pd.DataFrame, height: int = 300) -> go.Figure | None:
    """Did the coverage that week track the result? One point per matchweek."""
    d = perf.merge(sent, on="matchweek")
    d = d[d["article_count"] >= MIN_ARTICLES]
    if len(d) < 3:
        return None
    fig = go.Figure(
        go.Scatter(
            x=d["goal_difference"], y=d["avg_sentiment_score"], mode="markers+text", text=[f"MW{w} {r}" for w, r in zip(d["matchweek"], d["result"])],
            textposition="top center", textfont=dict(size=11, color=TEXT_3),
            marker=dict(size=13, symbol=[RESULT_SYMBOLS[r] for r in d["result"]], color=[RESULT_COLORS[r] for r in d["result"]],
                        line=dict(color=SURFACE, width=2)),
            customdata=d[["result", "article_count"]].to_numpy(),
            hovertemplate="Goal difference %{x:+d}<br>Sentiment <b>%{y:+.3f}</b><br>%{customdata[0]} · %{customdata[1]} articles<extra></extra>",
        )
    )
    style_fig(fig, height=height)
    fig.update_xaxes(title_text="Goal difference in the match", zeroline=True, zerolinecolor=BORDER, dtick=1)
    fig.update_yaxes(title_text="Sentiment that week", zeroline=True, zerolinecolor=BORDER)
    return fig


# ── Fixtures & accuracy ───────────────────────────────────────────────────────

def accuracy_chart(by_week: pd.DataFrame, baseline_log_loss: float | None, height: int = 300) -> go.Figure:
    fig = go.Figure(
        go.Bar(x=by_week["matchweek"], y=by_week["log_loss"], marker=dict(color=POS, line=dict(width=0)), name="Model",
               hovertemplate="Matchweek %{x}<br>Log loss <b>%{y:.3f}</b><extra></extra>")
    )
    if baseline_log_loss:
        fig.add_hline(y=baseline_log_loss, line=dict(color="#fab219", width=1.5, dash="dash"),
                      annotation_text="Baseline", annotation_font=dict(color=TEXT_2, size=11), annotation_position="top left")
    style_fig(fig, height=height)
    fig.update_xaxes(title_text="Matchweek", dtick=1)
    fig.update_yaxes(title_text="Log loss (lower is better)", rangemode="tozero")
    return fig


# ── Model evaluation ──────────────────────────────────────────────────────────

def dot_plot(df: pd.DataFrame, label: str, value: str, highlight: str = "blend", baseline: str = "prior",
             height: int = 340, decimals: int = 4) -> go.Figure:
    """Lollipop of one metric per model. A dot plot needs no zero baseline, so differences are not exaggerated."""
    d = df.sort_values(value, ascending=False)
    lo, hi = float(d[value].min()), float(d[value].max())
    pad = (hi - lo) * 0.12 or 0.01
    axis_lo = lo - pad
    colors = [lit(POS, 0.45) if m == highlight else (OTHER if m == baseline else "#4a6bb0") for m in d[label]]
    fig = go.Figure()
    fig.add_trace(go.Bar(y=d[label], x=d[value] - axis_lo, base=axis_lo, orientation="h", width=0.07, hoverinfo="skip",
                         marker=dict(color="rgba(143,168,222,0.35)", line=dict(width=0))))
    fig.add_trace(
        go.Scatter(
            y=d[label], x=d[value], mode="markers+text", text=[f"{v:.{decimals}f}" for v in d[value]], textposition="middle right",
            textfont=dict(color=TEXT_2, size=11), cliponaxis=False,
            marker=dict(size=[16 if m == highlight else 11 for m in d[label]], color=colors, line=dict(color=SURFACE, width=2)),
            hovertemplate="%{y}<br><b>%{x:.4f}</b><extra></extra>",
        )
    )
    style_fig(fig, height=height)
    fig.update_xaxes(range=[axis_lo, hi + pad * 2.2], title_text=f"{value} (lower is better, axis starts at {axis_lo:.2f})")
    fig.update_yaxes(showgrid=False, tickfont=dict(color=TEXT_2, size=12))
    fig.update_layout(bargap=0.3, margin=dict(l=8, r=16, t=8, b=8))
    return fig


_MODEL_STYLE = {
    "prior": (OTHER, "dash", 2.0),
    "elo_formula": ("#d95926", "solid", 2.2),
    "logit_elo": ("#199e70", "dot", 2.6),
    "poisson_glm": ("#c98500", "solid", 2.2),
    "xgb_full": ("#d55181", "solid", 2.2),
    "blend": (lit(POS, 0.4), "solid", 4.0),
}


def season_lines(df: pd.DataFrame, height: int = 340) -> go.Figure:
    fig = go.Figure()
    models = [c for c in df.columns if c != "season"]
    for i, model in enumerate(models):
        color, dash, width = _MODEL_STYLE.get(model, (SERIES[i % len(SERIES)], "solid", 2.2))
        fig.add_trace(
            go.Scatter(
                x=df["season"], y=df[model], mode="lines+markers", name=model,
                line=dict(color=color, width=width, dash=dash), marker=dict(size=7, color=color, line=dict(color=SURFACE, width=1.5)),
                hovertemplate=f"{model}<br>Season %{{x}} · <b>%{{y:.4f}}</b><extra></extra>",
            )
        )
    style_fig(fig, height=height, legend=True)
    fig.update_xaxes(title_text="Test season", dtick=1)
    fig.update_yaxes(title_text="Log loss (lower is better)")
    return fig


def champion_heatmap(df: pd.DataFrame, height: int = 300) -> go.Figure:
    """Probability given to the eventual champion at matchweek 35, per season and model."""
    seasons = df["season"].astype(str).tolist()
    models = [c for c in df.columns if c != "season"]
    z = [[float(df.iloc[r][m]) for m in models] for r in range(len(df))]
    return _annotated_heatmap(z, models, seasons, SEQUENTIAL, 0, 1, lambda v: f"{v:.0%}",
                              "Season %{y} · %{x}<br><b>%{z:.1%}</b> on the champion<extra></extra>", height=height, text_threshold=0.6,
                              follow_outline=False)
