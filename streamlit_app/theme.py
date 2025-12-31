"""
PLanalyst — Dashboard design system: "Midnight Transit".

A midnight-blue enamel ground, porcelain-white ticks and bright metro-line inks. The one
signature move is *following a club*: the followed club burns brightest on every chart and
the rest of the field recedes, like a chosen line on a transit map.

Colour jobs are kept apart: porcelain white is selection UI only, line inks are club identity,
a cobalt↔scarlet pair is sentiment polarity, a porcelain→enamel ramp is home/draw/away (so it never
collides with a club colour), and W/D/L use the fixed status colours and always carry a letter.
"""

from __future__ import annotations

from contextlib import contextmanager
from html import escape
from urllib.parse import quote

import plotly.graph_objects as go
import streamlit as st

# ── Tokens ────────────────────────────────────────────────────────────────────
BG = "#0A1128"          # midnight enamel
SURFACE = "#0F1A3B"     # panels
SURFACE_2 = "#152349"   # inputs, raised
BORDER = "#22345F"
BORDER_STRONG = "#35508F"
TEXT = "#F2F5FC"        # porcelain
TEXT_2 = "#B4C2E0"
TEXT_3 = "#8D9EC6"
PORCELAIN = "#EAF0FF"   # selection only, never a data colour

# Line inks (categorical, dark steps, validated against SURFACE): blue, orange, aqua, amber, magenta, green, violet, red
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
# Club inks: only five (orange, aqua, amber, magenta, violet). Blue is reserved for sentiment polarity,
# green and red for win/loss, so a club never shares a colour with a meaning. Validated adjacent on SURFACE.
TEAM_INKS = ["#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]
OTHER = "#5A6E9F"       # "everyone else"

# Sentiment polarity: cobalt (positive) ↔ scarlet (negative), enamel-grey midpoint
POS, NEG, NEUTRAL = "#4C86F0", "#e66767", "#3A4A78"
DIVERGING = [[0.0, NEG], [0.5, NEUTRAL], [1.0, POS]]

# Home / draw / away: a one-hue ramp that is deliberately not a club colour
HOME, DRAW_C, AWAY = "#E3EBFA", "#6F86B8", "#3F5599"

# Status colours (fixed): W / D / L
WIN, DRAW, LOSS = "#0ca30c", "#fab219", "#d03b3b"
RESULT_COLORS = {"W": WIN, "D": DRAW, "L": LOSS}

FONT = "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"


# Original pitch markings drawn from the standard pitch proportions (no league branding or logos)
_PITCH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 680" fill="none" stroke="#EAF0FF" stroke-width="3">'
    '<rect x="30" y="30" width="990" height="620"/><path d="M525 30V650"/><circle cx="525" cy="340" r="91"/>'
    '<circle cx="525" cy="340" r="4" fill="#EAF0FF"/>'
    '<rect x="30" y="138" width="165" height="404"/><rect x="30" y="234" width="55" height="212"/>'
    '<circle cx="125" cy="340" r="4" fill="#EAF0FF"/><path d="M195 282A91 91 0 0 1 195 398"/>'
    '<rect x="855" y="138" width="165" height="404"/><rect x="965" y="234" width="55" height="212"/>'
    '<circle cx="925" cy="340" r="4" fill="#EAF0FF"/><path d="M855 282A91 91 0 0 0 855 398"/></svg>'
)
# quotes, spaces and # are percent-encoded so the URI is safe inside a CSS url("...")
PITCH_URI = "data:image/svg+xml;utf8," + quote(_PITCH_SVG, safe="/:=")

# team name -> {"tla", "short", "crest"}; filled once per run from the API by the app shell
CLUBS: dict[str, dict] = {}


def set_clubs(clubs: dict[str, dict]) -> None:
    CLUBS.clear()
    CLUBS.update(clubs or {})


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lit(hex_color: str, amount: float = 0.38) -> str:
    """The followed club's colour: the same ink, burning brighter."""
    r, g, b = _rgb(hex_color)

    def mix(c: int) -> int:
        return int(c + (255 - c) * amount)

    return f"#{mix(r):02x}{mix(g):02x}{mix(b):02x}"


def dim(hex_color: str, alpha: float = 0.3) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha})"


def followed() -> str | None:
    """The club the visitor follows (set from the sidebar), or None."""
    value = st.session_state.get("follow")
    return value if value and not str(value).startswith("—") else None


def focus_color(team: str, base: str) -> str:
    """Followed club burns brightest, everyone else recedes; with nobody followed, plain ink."""
    follow = followed()
    if not follow:
        return base
    return lit(base) if team == follow else dim(base, 0.32)


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap');

:root {{
  --bg: {BG}; --surface: {SURFACE}; --surface-2: {SURFACE_2};
  --border: {BORDER}; --border-strong: {BORDER_STRONG};
  --text: {TEXT}; --text-2: {TEXT_2}; --text-3: {TEXT_3};
  --porcelain: {PORCELAIN}; --pos: {POS}; --neg: {NEG};
  --win: {WIN}; --draw: {DRAW}; --loss: {LOSS};
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
}}

/* Count-up figures: integers animated with CSS counters (final value kept in data-v) */
@property --hi {{ syntax: '<integer>'; initial-value: 0; inherits: false; }}
@property --lo {{ syntax: '<integer>'; initial-value: 0; inherits: false; }}
@counter-style pad3 {{ system: numeric; symbols: "0" "1" "2" "3" "4" "5" "6" "7" "8" "9"; pad: 3 "0"; }}
.count {{ animation: count-up 1100ms var(--ease) both; counter-reset: hi var(--hi) lo var(--lo); }}
.count.s::after {{ content: counter(lo); }}
.count.l::after {{ content: counter(hi) "," counter(lo, pad3); }}
@keyframes count-up {{ from {{ --hi: 0; --lo: 0; }} }}
@keyframes grow {{ from {{ transform: scaleX(0); }} }}
@keyframes pulse {{ 0%, 100% {{ box-shadow: 0 0 0 0 rgba(47,191,113,0.45); }} 60% {{ box-shadow: 0 0 0 6px rgba(47,191,113,0); }} }}

html, body, .stApp, button, input, select, textarea,
[class*="st-"]:not([data-testid="stIconMaterial"]):not([class*="material-symbols"]):not([class*="material-icons"]) {{
  font-family: {FONT};
  font-variant-numeric: tabular-nums;
}}
/* Streamlit's icon font: ligature text must never fall back to the UI font */
[data-testid="stIconMaterial"], [class*="material-symbols"] {{
  font-family: "Material Symbols Rounded" !important;
  font-feature-settings: "liga"; font-variant-numeric: normal; letter-spacing: normal; text-transform: none;
}}
/* Match night: floodlight glow, mown-grass stripes and faint pitch markings behind the content */
.stApp {{
  color: var(--text);
  background:
    radial-gradient(1100px 420px at 50% -120px, rgba(150,190,255,0.20), transparent 70%),
    repeating-linear-gradient(90deg, rgba(30,120,90,0.16) 0 96px, rgba(30,120,90,0) 96px 192px),
    var(--bg);
  background-attachment: fixed;
}}
.stApp::before {{
  content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none; opacity: 0.075;
  background: url("{PITCH_URI}") center 70% / min(1500px, 120vw) no-repeat;
}}
[data-testid="stAppViewContainer"] > section, [data-testid="stSidebar"], header[data-testid="stHeader"] {{ position: relative; z-index: 1; }}

/* Crests */
.crest {{ width: 22px; height: 22px; object-fit: contain; flex: none; filter: drop-shadow(0 1px 2px rgba(0,0,0,0.5)); transition: opacity 200ms var(--ease), filter 200ms var(--ease); }}
.crest.dim {{ opacity: 0.38; filter: grayscale(0.7) drop-shadow(0 1px 2px rgba(0,0,0,0.5)); }}
.crest.lit {{ filter: drop-shadow(0 0 9px rgba(234,240,255,0.7)); }}
.crest.mono {{ display: inline-grid; place-items: center; border-radius: 50%; border: 2px solid var(--text-3); background: var(--surface-2);
  color: var(--text); font-weight: 700; font-size: 0.55em; filter: none; }}

/* Contenders band: the title favourites on a mown-grass strip */
.band {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0; margin-bottom: 16px; border: 1px solid var(--border); border-radius: 14px; overflow: hidden;
  background: repeating-linear-gradient(90deg, rgba(30,120,90,0.20) 0 70px, rgba(20,90,80,0.10) 70px 140px), var(--surface); }}
.contender {{ padding: 18px 16px 16px; display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center; border-left: 1px solid rgba(180,194,224,0.12); transition: background 180ms var(--ease), opacity 200ms var(--ease); }}
.contender:first-child {{ border-left: none; }}
.contender:hover {{ background: rgba(234,240,255,0.06); }}
.contender .crest {{ width: 60px; height: 60px; }}
.contender .c-name {{ color: var(--text); font-weight: 600; font-size: 0.95rem; line-height: 1.2; }}
.contender .c-pct {{ color: var(--text); font-weight: 700; font-size: 1.35rem; letter-spacing: -0.01em; }}
.contender .c-bar {{ width: 70%; height: 4px; border-radius: 2px; background: rgba(180,194,224,0.18); overflow: hidden; }}
.contender .c-bar span {{ display: block; height: 100%; border-radius: 2px; transform-origin: left; animation: grow 900ms var(--ease) both; }}
.contender.dim {{ opacity: 0.55; }}
.contender.followed {{ background: rgba(234,240,255,0.10); }}

/* Club wall: all twenty crests */
.wall {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(64px, 1fr)); gap: 14px 10px; padding: 8px 4px 6px; }}
.wall .club {{ display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 0.7rem; color: var(--text-3); text-align: center; }}
.wall .crest {{ width: 44px; height: 44px; }}
.wall .club:hover .crest {{ transform: translateY(-2px) scale(1.06); }}

/* Team hero */
.team-hero {{ display: flex; align-items: center; gap: 22px; padding: 20px 24px; margin-bottom: 16px; border: 1px solid var(--border); border-radius: 14px;
  background: linear-gradient(90deg, rgba(15,26,59,0.2) 20%, rgba(15,26,59,0.7) 100%), url("{PITCH_URI}") right -20px center / 520px auto no-repeat,
    repeating-linear-gradient(90deg, rgba(30,120,90,0.20) 0 70px, rgba(20,90,80,0.08) 70px 140px), var(--surface); }}
.team-hero .crest {{ width: 84px; height: 84px; }}
.team-hero .t-name {{ font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); line-height: 1.1; }}
@media (max-width: 640px) {{ .team-hero {{ gap: 14px; padding: 14px; }} .team-hero .crest {{ width: 56px; height: 56px; }} .team-hero .t-name {{ font-size: 1.35rem; }} }}

/* Chrome: hide Streamlit's toolbar but keep the header so the sidebar toggle works on phones */
header[data-testid="stHeader"] {{ background: transparent; }}
/* The toolbar container also holds the sidebar-expand button, so hide only its actions */
[data-testid="stToolbarActions"], [data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stDecoration"], footer, #MainMenu {{ display: none !important; }}
[data-testid="stExpandSidebarButton"] {{ color: var(--porcelain); }}

.block-container {{ padding: 28px 40px 64px; max-width: 1360px; }}
@media (max-width: 768px) {{ .block-container {{ padding: 56px 16px 48px; }} }}

/* Text selection, caret, scrollbars, focus */
::selection {{ background: rgba(234,240,255,0.28); color: #fff; }}
* {{ caret-color: var(--porcelain); scrollbar-color: var(--border-strong) transparent; scrollbar-width: thin; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: var(--border-strong); border-radius: 8px; border: 2px solid var(--bg); }}
::-webkit-scrollbar-track {{ background: transparent; }}
:focus-visible {{ outline: 2px solid var(--porcelain) !important; outline-offset: 2px; border-radius: 6px; }}

/* Type scale (fixed rem, ~1.2 ratio) */
h1 {{ font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); padding: 0; margin: 0; }}
h2, h3 {{ font-size: 1rem; font-weight: 600; letter-spacing: -0.005em; color: var(--text); padding: 0; margin: 0; }}
p, li, label, .stMarkdown {{ color: var(--text-2); font-size: 0.94rem; line-height: 1.55; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: var(--text-3) !important; font-size: 0.8rem; }}
a {{ color: var(--porcelain); text-underline-offset: 3px; }}
hr {{ border-color: var(--border) !important; margin: 24px 0 !important; }}

/* Sidebar */
section[data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--border); }}
section[data-testid="stSidebar"] > div {{ padding-top: 8px; }}
[data-testid="stSidebarNav"] {{ padding-top: 4px; }}
[data-testid="stSidebarNav"] a {{
  border-radius: 8px; padding: 8px 12px; color: var(--text-2); font-weight: 500; font-size: 0.9rem;
  transition: background 160ms var(--ease), color 160ms var(--ease);
}}
[data-testid="stSidebarNav"] a:hover {{ background: var(--surface-2); color: var(--text); }}
/* Selection is porcelain: a filled ticket, never a data hue */
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: var(--porcelain); color: {BG}; font-weight: 600; }}
[data-testid="stSidebarNav"] a[aria-current="page"] * {{ color: {BG} !important; }}
.side-label {{ font-size: 0.78rem; color: var(--text-3); font-weight: 600; padding: 14px 4px 4px; }}

/* Panels: st.container(border=True). Streamlit 1.5x+ has no border-wrapper element, so a panel is the vertical
   block that holds a .panel-head. Its layout wrapper grows so panels in one row share a height. */
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .panel-head) {{
  background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 14px !important;
  padding: 10px 16px 14px !important; box-shadow: none !important; flex: 1 1 auto;
  transition: border-color 200ms var(--ease);
}}
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .panel-head):hover {{ border-color: var(--border-strong) !important; }}
div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .panel-head) {{ flex: 1 1 auto; }}
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .nostretch),
div[data-testid="stLayoutWrapper"]:has(> div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"] .nostretch) {{ flex: 0 0 auto; }}
div[data-testid="stColumn"] {{ display: flex; flex-direction: column; }}
div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {{ flex: 1; }}
.panel-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 6px 0 2px; }}
.panel-title {{ font-size: 0.95rem; font-weight: 600; color: var(--text); }}
.panel-note {{ font-size: 0.78rem; color: var(--text-3); }}

/* Page header */
.page-head {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; flex-wrap: wrap; margin-bottom: 22px;
  padding: 22px 26px; border: 1px solid var(--border); border-radius: 14px;
  background: linear-gradient(90deg, var(--surface) 30%, rgba(15,26,59,0.45) 100%), url("{PITCH_URI}") right -30px center / 600px auto no-repeat, var(--surface); }}
.page-title {{ font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); line-height: 1.15; }}
.page-sub {{ color: var(--text-2); font-size: 0.92rem; margin-top: 6px; max-width: 62ch; }}
.chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.chip {{
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); font-size: 0.78rem; font-weight: 500;
}}
.chip b {{ color: var(--text); font-weight: 600; }}
.dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); display: inline-block; }}
.dot.ok {{ background: #2fbf71; animation: pulse 2.4s ease-out infinite; }}
.dot.bad {{ background: var(--loss); box-shadow: 0 0 0 3px rgba(208,59,59,0.25); }}

/* Stat strip: one panel, hairline-separated stats */
.stats {{ display: grid; grid-template-columns: repeat(var(--n, 4), minmax(0, 1fr)); background: var(--surface);
  border: 1px solid var(--border); border-radius: 14px; margin-bottom: 16px; overflow: hidden; }}
.stat {{ padding: 16px 20px; border-left: 1px solid var(--border); min-width: 0; }}
.stat:first-child {{ border-left: none; }}
.stat-label {{ font-size: 0.78rem; color: var(--text-3); font-weight: 500; }}
.stat-value {{ font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; color: var(--text); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.stat-foot {{ font-size: 0.78rem; color: var(--text-2); margin-top: 2px; }}
@media (max-width: 900px) {{
  .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .stat:nth-child(odd) {{ border-left: none; }}
  .stat:nth-child(n+3) {{ border-top: 1px solid var(--border); }}
}}

/* Ranked odds list drawn as a transit route: numbered station roundels on one line */
.rank-row {{ position: relative; display: grid; grid-template-columns: 24px minmax(0,1.4fr) minmax(0,2fr) 58px; align-items: center; gap: 12px; padding: 7px 8px; margin: 0 -8px; border-radius: 8px; transition: background 160ms var(--ease); }}
.rank-row::before {{ content: ""; position: absolute; left: 18.5px; top: 0; bottom: 0; width: 3px; background: var(--border-strong); }}
.rank-row:first-child::before {{ top: 50%; }}
.rank-row:last-child::before {{ bottom: 50%; }}
.rank-row:hover {{ background: rgba(234,240,255,0.05); }}
.rank-row.dim {{ opacity: 0.62; }}
.rank-row.followed {{ background: rgba(234,240,255,0.07); }}
.roundel {{ position: relative; z-index: 1; width: 24px; height: 24px; border-radius: 50%; border: 2px solid var(--text-3); background: var(--surface);
  box-shadow: 0 0 0 3px var(--surface); display: grid; place-items: center; font-size: 0.74rem; font-weight: 700; color: var(--text); }}
.rank-team {{ color: var(--text); font-size: 0.92rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center; gap: 9px; }}
.rank-row.followed .rank-team {{ font-weight: 700; }}
.bar-track {{ height: 8px; background: var(--surface-2); border-radius: 4px; overflow: hidden; }}
.bar-fill {{ height: 100%; border-radius: 4px; transform-origin: left; animation: grow 800ms var(--ease) both; }}
.rank-val {{ color: var(--text); font-size: 0.88rem; font-weight: 600; text-align: right; }}
@media (max-width: 640px) {{
  .rank-row {{ grid-template-columns: 24px minmax(112px, 1.7fr) minmax(32px, 0.7fr) 52px; gap: 8px; }}
  .stat {{ padding: 14px 16px; }}
  .stat-value {{ white-space: normal; font-size: 1.25rem; }}
  .page-title {{ font-size: 1.5rem; }}
  .panel-head {{ flex-direction: column; align-items: flex-start; gap: 2px; }}
}}

/* Fixture probability rails */
.fx {{ display: grid; grid-template-columns: minmax(0,1fr) auto minmax(0,1fr); gap: 6px 12px; align-items: baseline; padding: 12px 8px; margin: 0 -8px; border-top: 1px solid var(--border); border-radius: 8px; transition: background 160ms var(--ease); }}
.fx:first-child {{ border-top: none; }}
.fx:hover {{ background: rgba(234,240,255,0.05); }}
.fx.followed {{ background: rgba(234,240,255,0.07); }}
.fx-time {{ grid-column: 1 / -1; color: var(--text-3); font-size: 0.76rem; }}
.fx-home {{ display: flex; align-items: center; justify-content: flex-end; gap: 9px; color: var(--text); font-weight: 550; font-size: 0.92rem; }}
.fx-away {{ display: flex; align-items: center; gap: 9px; color: var(--text); font-weight: 550; font-size: 0.92rem; }}
.fx-mid {{ color: var(--text-3); font-size: 0.78rem; min-width: 34px; text-align: center; }}
.fx-mid.score {{ color: var(--text); font-weight: 700; font-size: 0.95rem; }}
.fx-rail {{ grid-column: 1 / -1; }}
.rail {{ display: flex; height: 26px; border-radius: 6px; overflow: hidden; gap: 2px; background: var(--surface); }}
.rail > div {{ display: grid; place-items: center; font-size: 0.78rem; font-weight: 700; min-width: 0; overflow: hidden; }}
.rail .h {{ background: {HOME}; color: {BG}; }} .rail .d {{ background: {DRAW_C}; color: {BG}; }} .rail .a {{ background: {AWAY}; color: #fff; }}
.legend {{ display: flex; gap: 16px; font-size: 0.78rem; color: var(--text-2); margin-top: 10px; flex-wrap: wrap; }}
.legend i {{ display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 6px; }}

/* Form strip */
.form {{ display: flex; gap: 6px; flex-wrap: wrap; }}
.form span {{ width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; font-weight: 700; font-size: 0.8rem; color: #fff; }}

/* Streamlit widgets */
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div, .stNumberInput input {{
  background: var(--surface-2) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; color: var(--text) !important;
  transition: border-color 160ms var(--ease);
}}
div[data-baseweb="select"] > div:hover, div[data-baseweb="input"] > div:hover {{ border-color: var(--border-strong) !important; }}
div[data-baseweb="popover"] ul {{ background: var(--surface-2) !important; border: 1px solid var(--border-strong); }}
.stSlider [role="slider"] {{ background: var(--porcelain) !important; box-shadow: 0 0 0 4px rgba(234,240,255,0.18); }}
.stSlider [data-baseweb="slider"] > div > div {{ background: var(--border-strong); }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid var(--border); }}
.stTabs [data-baseweb="tab"] {{ color: var(--text-2); font-weight: 500; padding: 8px 14px; border-radius: 8px 8px 0 0; }}
.stTabs [aria-selected="true"] {{ color: #fff; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: var(--porcelain); height: 2px; }}
.stButton > button {{
  background: var(--surface-2); border: 1px solid var(--border-strong); color: var(--text); border-radius: 10px; font-weight: 500;
  transition: background 160ms var(--ease), border-color 160ms var(--ease);
}}
.stButton > button:hover {{ border-color: var(--porcelain); background: #1b2c5a; color: #fff; }}
[data-testid="stExpander"] {{ border: 1px solid var(--border) !important; border-radius: 12px; background: var(--surface); }}
[data-testid="stExpander"] summary {{ color: var(--text-2); font-weight: 500; }}
[data-testid="stDataFrame"] {{ border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
[data-testid="stAlert"] {{ border-radius: 12px; border: 1px solid var(--border); background: var(--surface-2); }}
[data-testid="stPlotlyChart"] {{ border-radius: 10px; }}

.empty {{ padding: 28px 8px; color: var(--text-2); font-size: 0.9rem; max-width: 60ch; }}
.empty b {{ color: var(--text); display: block; margin-bottom: 4px; font-weight: 600; }}
.note {{ color: var(--text-3); font-size: 0.8rem; margin-top: 8px; }}

@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
  .count.s::after, .count.l::after {{ content: attr(data-v); }}
}}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ── Components ────────────────────────────────────────────────────────────────

class Html:
    """Marks a stat value as trusted HTML (built by `count`)."""

    def __init__(self, html: str):
        self.html = html


def count(value: int, suffix: str = "") -> str:
    """HTML for an integer that counts up on load (CSS counters); the final value is kept in data-v."""
    suffix_html = escape(suffix)
    if value >= 1000:
        hi, lo = divmod(int(value), 1000)
        return f'<span class="count l" style="--hi:{hi};--lo:{lo}" data-v="{value:,}"></span>{suffix_html}'
    return f'<span class="count s" style="--lo:{int(value)}" data-v="{int(value)}"></span>{suffix_html}'


def counted(value: int, suffix: str = "") -> Html:
    return Html(count(value, suffix))


def page_header(title: str, subtitle: str = "", chips: list[str] | None = None) -> None:
    chip_html = "".join(f'<span class="chip">{c}</span>' for c in (chips or []))
    sub = f'<div class="page-sub">{escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="page-head"><div><div class="page-title">{escape(title)}</div>{sub}</div>'
        f'<div class="chips">{chip_html}</div></div>',
        unsafe_allow_html=True,
    )


def chip(label: str, value: str) -> str:
    return f"{escape(label)} <b>{escape(str(value))}</b>"


def api_status_chip(ok: bool) -> str:
    cls, text = ("ok", "API connected") if ok else ("bad", "API offline")
    return f'<span class="dot {cls}"></span>{text}'


@contextmanager
def panel(title: str, note: str = "", stretch: bool = True):
    """A bordered panel with a title row. Panels never nest. Panels in a row share a height unless stretch=False."""
    with st.container(border=True):
        note_html = f'<span class="panel-note">{escape(note)}</span>' if note else ""
        head_class = "panel-head" if stretch else "panel-head nostretch"
        st.markdown(
            f'<div class="{head_class}"><span class="panel-title">{escape(title)}</span>{note_html}</div>',
            unsafe_allow_html=True,
        )
        yield


def stat_strip(items: list[tuple]) -> None:
    """One panel of hairline-separated stats: (label, value, footnote). A value built with `counted` counts up on load."""
    cells = []
    for label, value, foot in items:
        shown = value.html if isinstance(value, Html) else escape(str(value))
        cells.append(
            f'<div class="stat"><div class="stat-label">{escape(label)}</div>'
            f'<div class="stat-value">{shown}</div><div class="stat-foot">{escape(foot)}</div></div>'
        )
    st.markdown(f'<div class="stats" style="--n:{len(items)}">{"".join(cells)}</div>', unsafe_allow_html=True)


def empty_state(title: str, body: str) -> None:
    st.markdown(f'<div class="empty"><b>{escape(title)}</b>{escape(body)}</div>', unsafe_allow_html=True)


def api_error() -> None:
    empty_state(
        "Can't reach the API",
        "The dashboard reads everything through the FastAPI service. Start it (or `docker compose up -d`) and reload.",
    )


def ranked_bars(rows: list[tuple[str, float, str]], max_value: float, fmt: str = "{:.1%}") -> None:
    """Ranked list drawn as a transit route: (label, value, ink). Each club is a numbered station roundel in its ink;
    the followed club's station is filled and lit, the rest of the route recedes."""
    follow = followed()
    html = []
    for i, (label, value, color) in enumerate(rows, 1):
        width = 0 if max_value <= 0 else max(0.0, min(100.0, value / max_value * 100))
        mine = follow == label
        cls = "followed" if mine else ("dim" if follow else "")
        shown = lit(color) if mine else color
        roundel = (
            f"background:{shown};border-color:{shown};color:{BG};box-shadow:0 0 0 3px {SURFACE},0 0 14px {dim(color, 0.8)}"
            if mine else f"border-color:{shown}"
        )
        glow = f"box-shadow:0 0 12px {dim(color, 0.7)};" if mine else ""
        html.append(
            f'<div class="rank-row {cls}"><span class="roundel" style="{roundel}">{i}</span>'
            f'<span class="rank-team">{crest(label, 22)}{escape(label)}</span>'
            f'<span class="bar-track"><span class="bar-fill" style="display:block;width:{width:.1f}%;background:{shown};{glow}"></span></span>'
            f'<span class="rank-val">{fmt.format(value)}</span></div>'
        )
    st.markdown("".join(html), unsafe_allow_html=True)


def crest(team: str, size: int = 22) -> str:
    """A club crest (from the football-data.org feed) or, if none is known, a monogram badge in the club's ink.

    Following a club lights its crest and dims everyone else's.
    """
    info = CLUBS.get(team, {})
    follow = followed()
    state = "lit" if follow == team else ("dim" if follow else "")
    url = info.get("crest")
    if url:
        return f'<img class="crest {state}" src="{escape(url)}" width="{size}" height="{size}" alt="" loading="lazy">'
    tla = info.get("tla") or team[:3].upper()
    return f'<span class="crest mono {state}" style="width:{size}px;height:{size}px">{escape(tla)}</span>'


def contender_band(rows: list[tuple[str, float, str]], max_value: float) -> None:
    """The title favourites as a band of big crests: (team, probability, ink)."""
    follow = followed()
    tiles = []
    for team, prob, ink in rows:
        cls = "followed" if follow == team else ("dim" if follow else "")
        width = 0 if max_value <= 0 else prob / max_value * 100
        tiles.append(
            f'<div class="contender {cls}">{crest(team, 60)}<div class="c-name">{escape(team)}</div>'
            f'<div class="c-pct">{prob:.1%}</div><div class="c-bar"><span style="width:{width:.1f}%;background:{lit(ink) if follow == team else ink}"></span></div></div>'
        )
    st.markdown(f'<div class="band">{"".join(tiles)}</div>', unsafe_allow_html=True)


def club_wall(teams: list[tuple[str, str]]) -> None:
    """Every club's crest in a grid: (team, hover text)."""
    cells = "".join(
        f'<div class="club" title="{escape(hint)}">{crest(team, 44)}<span>{escape(CLUBS.get(team, {}).get("tla", team[:3].upper()))}</span></div>'
        for team, hint in teams
    )
    st.markdown(f'<div class="wall">{cells}</div>', unsafe_allow_html=True)


def team_hero(team: str, chips: list[str]) -> None:
    chip_html = "".join(f'<span class="chip">{c}</span>' for c in chips)
    st.markdown(
        f'<div class="team-hero">{crest(team, 84)}<div><div class="t-name">{escape(team)}</div>'
        f'<div class="chips" style="margin-top:10px">{chip_html}</div></div></div>',
        unsafe_allow_html=True,
    )


def crest_url(team: str) -> str | None:
    return CLUBS.get(team, {}).get("crest") or None


def form_strip(results: list[str]) -> None:
    spans = "".join(
        f'<span style="background:{RESULT_COLORS.get(r, OTHER)}" title="{r}">{escape(r)}</span>' for r in results
    )
    st.markdown(f'<div class="form">{spans}</div>', unsafe_allow_html=True)


def prob_rail(p_home: float, p_draw: float, p_away: float) -> str:
    def seg(cls: str, p: float) -> str:
        label = f"{p:.0%}" if p >= 0.09 else ""
        return f'<div class="{cls}" style="flex:{max(p, 0.001):.4f}" title="{p:.1%}">{label}</div>'

    return f'<div class="rail">{seg("h", p_home)}{seg("d", p_draw)}{seg("a", p_away)}</div>'


def fixture_row(f: dict) -> str:
    """One fixture: kick-off, the two clubs (or the score once played) and the H/D/A probability rail."""
    import pandas as pd

    when = pd.to_datetime(f["kickoff"], utc=True, errors="coerce")
    stamp = "Kick-off TBC" if pd.isna(when) else when.strftime("%a %d %b · %H:%M UTC")
    played = f.get("played") and f.get("score_home") is not None
    mid = f'<div class="fx-mid score">{int(f["score_home"])}–{int(f["score_away"])}</div>' if played else '<div class="fx-mid">v</div>'
    cls = "followed" if followed() in (f["home_team"], f["away_team"]) else ""
    return (
        f'<div class="fx {cls}"><div class="fx-time">{stamp}</div>'
        f'<div class="fx-home">{escape(f["home_team"])}{crest(f["home_team"], 24)}</div>{mid}<div class="fx-away">{crest(f["away_team"], 24)}{escape(f["away_team"])}</div>'
        f'<div class="fx-rail">{prob_rail(f["p_home"], f["p_draw"], f["p_away"])}</div></div>'
    )


FIXTURE_LEGEND = (
    f'<div class="legend"><span><i style="background:{HOME}"></i>Home win</span>'
    f'<span><i style="background:{DRAW_C}"></i>Draw</span><span><i style="background:{AWAY}"></i>Away win</span></div>'
)


# ── Colour helpers ────────────────────────────────────────────────────────────

def team_colors(ranked_teams: list[str]) -> dict[str, str]:
    """Stable team → line ink: the top 5 by title odds take fixed inks; a followed outsider burns porcelain.

    Colour follows the entity: the same team keeps the same ink on every page in a session.
    """
    mapping = {team: TEAM_INKS[i] for i, team in enumerate(ranked_teams[: len(TEAM_INKS)])}
    follow = followed()
    if follow and follow not in mapping:
        mapping[follow] = PORCELAIN
    return mapping


def color_for(team: str, mapping: dict[str, str]) -> str:
    return mapping.get(team, OTHER)


# ── Plotly ────────────────────────────────────────────────────────────────────

def style_fig(fig: go.Figure, height: int = 360, legend: bool = False) -> go.Figure:
    """Apply the shared chart look: transparent ground, recessive grid, tidy hover."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12, color=TEXT_2),
        margin=dict(l=8, r=8, t=8, b=8),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=12, color=TEXT_2)),
        hoverlabel=dict(bgcolor="#16254F", bordercolor=BORDER_STRONG, font=dict(family=FONT, size=12, color=TEXT)),
        hovermode="closest",
    )
    axis = dict(gridcolor="rgba(180,194,224,0.08)", zeroline=False, linecolor=BORDER, tickfont=dict(color=TEXT_3, size=11),
                title_font=dict(color=TEXT_3, size=12))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def show(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False}, key=key)


def donut(labels: list[str], values: list[float], colors: list[str], center_text: str, center_sub: str = "",
          height: int = 330, legend: bool = True) -> go.Figure:
    """Donut with panel-coloured gaps, the headline value in the hole and a legend so every slice is named.

    The followed club's slice is pulled out and burns brightest; the rest recede.
    """
    follow = followed()
    follow = follow if follow in labels else None  # only club-labelled slices take the focus
    pull = [0.07 if follow and label == follow else 0 for label in labels]
    if follow:
        colors = [lit(c) if label == follow else dim(c, 0.35) for label, c in zip(labels, colors)]
    fig = go.Figure(
        go.Pie(
            labels=labels, values=values, hole=0.66, sort=False, direction="clockwise", pull=pull,
            marker=dict(colors=colors, line=dict(color=SURFACE, width=2)),
            textinfo="none",
            hovertemplate="%{label}<br><b>%{percent}</b><extra></extra>",
        )
    )
    annotations = [dict(text=f"<b>{escape(center_text)}</b>", x=0.5, y=0.55 if center_sub else 0.5, showarrow=False,
                        font=dict(size=24, color=TEXT, family=FONT))]
    if center_sub:
        annotations.append(dict(text=escape(center_sub), x=0.5, y=0.44, showarrow=False, font=dict(size=12, color=TEXT_3, family=FONT)))
    style_fig(fig, height=height, legend=legend)
    fig.update_layout(
        annotations=annotations, margin=dict(l=0, r=0, t=4, b=0),
        legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5, font=dict(size=11, color=TEXT_2)),
    )
    return fig
