---
name: PLanalyst
description: Midnight Transit, a title-race dashboard where the club you follow burns brightest and the rest of the field recedes.
colors:
  midnight-enamel: "#0A1128"
  panel-enamel: "#0F1A3B"
  raised-enamel: "#152349"
  enamel-hairline: "#22345F"
  enamel-hairline-strong: "#35508F"
  porcelain-text: "#F2F5FC"
  porcelain-text-2: "#B4C2E0"
  porcelain-text-3: "#8D9EC6"
  porcelain-selection: "#EAF0FF"
  ink-orange: "#d95926"
  ink-aqua: "#199e70"
  ink-amber: "#c98500"
  ink-magenta: "#d55181"
  ink-violet: "#9085e9"
  field-grey: "#5A6E9F"
  sentiment-positive: "#4C86F0"
  sentiment-negative: "#e66767"
  sentiment-neutral: "#3A4A78"
  home-win: "#E3EBFA"
  draw-mid: "#6F86B8"
  away-win: "#3F5599"
  status-win: "#0ca30c"
  status-draw: "#fab219"
  status-loss: "#d03b3b"
typography:
  title:
    fontFamily: "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.75rem"
    fontWeight: 650
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  stat:
    fontFamily: "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1.5rem"
    fontWeight: 650
    letterSpacing: "-0.02em"
  heading:
    fontFamily: "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    letterSpacing: "-0.005em"
  body:
    fontFamily: "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.94rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "'Source Sans 3', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "0.78rem"
    fontWeight: 500
    letterSpacing: "normal"
rounded:
  sm: "4px"
  md: "8px"
  input: "10px"
  lg: "12px"
  panel: "14px"
  pill: "999px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  page-x: "40px"
components:
  panel:
    backgroundColor: "{colors.panel-enamel}"
    textColor: "{colors.porcelain-text}"
    rounded: "{rounded.panel}"
    padding: "10px 16px 14px"
  stat-strip:
    backgroundColor: "{colors.panel-enamel}"
    textColor: "{colors.porcelain-text}"
    rounded: "{rounded.panel}"
  stat-cell:
    padding: "16px 20px"
  chip:
    backgroundColor: "{colors.raised-enamel}"
    textColor: "{colors.porcelain-text-2}"
    rounded: "{rounded.pill}"
    padding: "5px 10px"
  button:
    backgroundColor: "{colors.raised-enamel}"
    textColor: "{colors.porcelain-text}"
    rounded: "{rounded.input}"
  button-hover:
    backgroundColor: "#1b2c5a"
    textColor: "#ffffff"
  input:
    backgroundColor: "{colors.raised-enamel}"
    textColor: "{colors.porcelain-text}"
    rounded: "{rounded.input}"
  nav-link:
    textColor: "{colors.porcelain-text-2}"
    rounded: "{rounded.md}"
    padding: "8px 12px"
  nav-link-active:
    backgroundColor: "{colors.porcelain-selection}"
    textColor: "{colors.midnight-enamel}"
  form-tile:
    textColor: "#ffffff"
    rounded: "{rounded.md}"
    size: "30px"
  prob-rail:
    backgroundColor: "{colors.panel-enamel}"
    rounded: "{rounded.sm}"
    height: "26px"
---

# Design System: PLanalyst

## Overview

**Creative North Star: "Midnight Transit"**

A transit map for the title race. The ground is midnight-blue enamel, labels are porcelain-white ticks, and clubs are bright metro-line inks. The one signature move is following a club: pick one in the sidebar and it burns brightest on every chart, list and fixture, while the other clubs recede to translucent ink, like a chosen line on a network map. Navigation, controls and layout stay standard; the world lends only type, palette, density and that one move.

The mood is calm, dense and legible: fixed rem type, hairline panels, tabular figures, almost no ornament. Depth is tonal, not shadowed. Glow is reserved for the followed club. The system rejects the generic dark dashboard with gradient-text glass.

**Key Characteristics:**
- Three enamel surface steps with hairline borders; no resting shadows.
- Colour has one job each: selection, club identity, sentiment polarity, home/draw/away, win/draw/loss.
- Followed club = lit ink plus glow; everyone else = same ink at 32% alpha.
- Source Sans 3 with tabular numerals everywhere.
- Thin-data states are labelled and left blank, never ranked or coloured as a finding.

## Colors

A deep navy field with one pale selection colour and a small set of saturated line inks, each ink bound to a single meaning.

### Primary
- **Porcelain Selection** (`porcelain-selection`): selection and focus only: active nav ticket, focus ring, caret, slider thumb, tab underline, followed-row outline, link colour. It is never a data colour. The one exception is recorded in the rule below.

### Secondary (club identity)
- **Line Inks** (`ink-orange`, `ink-aqua`, `ink-amber`, `ink-magenta`, `ink-violet`): the five club inks. The top five clubs by title odds take them in that order and keep them on every page in a session. Only five exist so a club never shares a colour with a meaning.
- **Field Grey** (`field-grey`): everyone else, "rest of the field", article-volume bars, the baseline model.

### Tertiary (meaning colours)
- **Sentiment Polarity** (`sentiment-positive` cobalt, `sentiment-negative` scarlet, `sentiment-neutral` enamel-grey midpoint): diverging bars and heatmap. Blue is reserved for positive sentiment (and the accuracy/model highlight).
- **Home / Draw / Away ramp** (`home-win`, `draw-mid`, `away-win`): a one-hue porcelain-to-enamel ramp for fixture probability rails and their legend, deliberately not a club colour.
- **Status W / D / L** (`status-win`, `status-draw`, `status-loss`): form tiles, result donut, result scatter. Always paired with the letter W/D/L and, in charts, a marker shape (circle, diamond, square).

### Neutral
- **Midnight Enamel** (`midnight-enamel`): page ground; also the dark text on porcelain and on light rail segments.
- **Panel Enamel** (`panel-enamel`): sidebar, panels, stat strip, expanders, chart slice gaps and marker rings.
- **Raised Enamel** (`raised-enamel`): inputs, buttons, chips, bar tracks.
- **Enamel Hairlines** (`enamel-hairline`, `enamel-hairline-strong`): panel borders and dividers; the strong step for hover, scrollbars and the transit route line.
- **Porcelain Text 1/2/3** (`porcelain-text`, `-2`, `-3`): primary, body and tertiary/caption text.

### Named Rules
**The Porcelain Rule.** Porcelain is selection UI only. It never encodes data. A followed club that has no ink of its own (outside the top five) is the single exception: it burns porcelain.

**The One Meaning Rule.** A hue carries one meaning. Club inks are never used for polarity or result; blue, green and red are kept out of the club set.

**The Follow Rule.** Anything that shows clubs must route its colour through `focus_color`, `lit` and `dim`: followed club lit (+38% toward white), others at 0.32 alpha, nobody followed means plain ink.

**The Never Colour Alone Rule.** Win, draw and loss always carry a letter and, in charts, a marker shape.

## Typography

**Display Font:** Source Sans 3 (with ui-sans-serif, system-ui, Segoe UI, sans-serif)
**Body Font:** Source Sans 3 (same)
**Label/Mono Font:** none; tabular figures from `font-variant-numeric: tabular-nums` on everything.

**Character:** A humanist signage sans with unslashed zeros, chosen over Atkinson Hyperlegible Next because slashed zeros made dates and percentages misread. Weights 400 to 700 are loaded; hierarchy comes from size and weight, not case or tracking.

### Hierarchy
- **Title** (650, 1.75rem, 1.15, -0.02em): page title; 1.5rem under 640px.
- **Stat** (650, 1.5rem, -0.02em): stat-strip value; 1.25rem under 640px. Integers count up on load.
- **Heading** (600, 1rem to 0.95rem): panel titles, h2/h3.
- **Body** (400, 0.94rem, 1.55): paragraphs and labels in text-2; page subtitle 0.92rem capped at 62ch.
- **Label** (500 to 600, 0.78rem to 0.8rem): chips, stat labels, panel notes, legends, captions in text-3.
- **Chart text** (Plotly, 12px axis and legend, 11px ticks and annotations).

### Named Rules
**The Tabular Rule.** Every figure uses tabular numerals so columns of odds and counts align.

**The Sentence Case Rule.** Labels are sentence case at normal tracking; hierarchy is built from size, weight and the three text greys.

## Layout

A standard Streamlit shell: left sidebar (logo, nav, follow-a-club select, live status) and a single main column capped at 1360px with 28px 40px 64px padding (56px 16px 48px under 768px). Pages open with a page header (title, subtitle, status chips), then a stat strip, then panels in equal-height rows. Spacing is a 4/8-based rhythm: 6, 8, 12, 16, 24px steps; panels sit 16px apart and horizontal rules take 24px margin. Panels never nest. Stat strip drops from n columns to 2 under 900px; ranked rows and headers compress under 640px. Chart heights follow content (about 26 to 28px per row, 280 to 560px otherwise).

## Elevation & Depth

Tonal layering, flat at rest. Ground, panel and raised enamel steps with 1px hairlines carry all depth. There are no resting box-shadows; the only shadows are state and signal: the followed club's glow (bar glow, roundel halo, 12px line underlay), the live-status pulse, and the 3px ring in the panel colour that makes roundels and chart markers read as stations.

### Named Rules
**The Flat-By-Default Rule.** Panels never carry shadows; hover only lifts the border to the strong hairline.

**The Glow Is Following Rule.** Glow signals the followed club or live status. It is never decoration.

## Shapes

Soft enamel tiles: 14px panels and stat strip, 12px expanders, tables and alerts, 10px inputs and buttons, 8px nav links, form tiles and rank rows, 6px rails and focus outline, pills (999px) for chips. Chart marks follow the transit map: round station roundels (24px numbered, 2px club-ink border), markers ringed in the panel colour, donuts with a 0.66 hole and panel-coloured slice gaps, heatmap cells with 3px gaps. Result markers are circle (win), diamond (draw), square (loss). The ranked list is drawn as one 3px route line through the roundels.

## Components

### Buttons
- **Shape:** 10px radius, 1px strong hairline.
- **Default:** raised enamel fill, porcelain text, weight 500.
- **Hover / Focus:** border turns porcelain and fill lifts one step (`#1b2c5a`); 160ms ease-out. Focus is a 2px porcelain outline with 2px offset.

### Chips
- **Style:** pill, raised enamel, hairline, text-2 at 0.78rem with the value in bold text-1. Used in the page header for status such as the API connection (green pulsing dot or red dot).

### Cards / Containers
- **Panel:** panel enamel, 1px hairline, 14px radius, title row (600 title left, text-3 note right), never nested.
- **Stat strip:** one panel of hairline-separated cells (label, 1.5rem value, footnote).

### Inputs / Fields
- **Style:** raised enamel, 1px hairline, 10px radius; hover moves to the strong hairline; popovers use raised enamel with a strong hairline. Slider thumb and tab underline are porcelain.

### Navigation
- **Style:** sidebar on panel enamel; links 8px radius, 0.9rem weight 500, text-2. Hover raises to raised enamel. Active is a filled porcelain ticket with midnight text. Sidebar toggle is porcelain on mobile.

### Followed Club (signature)
`lit()` mixes a club ink 38% toward white; `dim()` drops others to alpha 0.32; `focus_color()` applies both, and `team_colors()` maps the top five clubs to fixed inks. The followed club gets a lit ink, a glow, a porcelain outline in heatmaps and scatters, a larger marker, a pulled-out donut slice, a filled roundel and bold row text; unfollowed rows go to 62% opacity.

### Ranked Route
Numbered station roundels on a single route line with an 8px progress bar and right-aligned value; bars grow in over 800ms.

### Probability Rail
A 26px segmented bar per fixture: home (porcelain, dark text), draw (mid), away (enamel-blue, white text), labels shown only at 9% or more, with a legend beneath.

### Form Strip
30px rounded tiles with W, D or L on the status colour.

### Charts
Plotly on a transparent ground, grid at 8% alpha, text-2/3 ticks, hover label on raised enamel. Form follows the job: donuts for share, dot and range for magnitude and uncertainty, diverging bars and heatmap for polarity, glow lines for change over time. Thin coverage (fewer than 8 articles) is left blank, not ranked; hollow markers flag thin weeks.

## Do's and Don'ts

### Do:
- **Do** route every club-showing chart through `focus_color` / `lit` / `dim` so the followed club burns and the field recedes.
- **Do** keep porcelain (`#EAF0FF`) for selection and focus only.
- **Do** pair W/D/L colour with the letter and a marker shape.
- **Do** label sample size and leave thin-data cells blank rather than coloured.
- **Do** keep club inks to the five set and the same club on the same ink on every page.
- **Do** build depth from the three enamel steps and hairlines; keep motion short (160 to 200ms ease, 800 to 1100ms for count-up and bar growth) and honour `prefers-reduced-motion`.
- **Do** use tabular numerals and sentence-case labels.

### Don't:
- **Don't** use blue, green or red as a club ink; they mean positive sentiment, win and loss.
- **Don't** use a club ink or porcelain for polarity or the home/draw/away ramp.
- **Don't** add resting shadows, gradient text or glass effects.
- **Don't** nest panels.
- **Don't** reintroduce Atkinson Hyperlegible Next; its slashed zeros misread dates and percentages.
- **Don't** hard-code new hexes inside chart code; add a token in `theme.py` first.
