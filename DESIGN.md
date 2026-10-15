---
name: Ontario Sunshine List
description: Ontario's public sector salary disclosure, set like the newspaper's agate tables.
colors:
  newsprint: "#e6e6e3"
  newsprint-raised: "#efefec"
  ink: "#161616"
  ink-soft: "#3d3d3a"
  rule-grey: "#8c8c88"
  process-blue: "#1f3a93"
  spot-ink: "#ffffff"
  error-red: "#a3221a"
  night-paper: "#121212"
  night-paper-raised: "#1c1c1b"
  night-ink: "#e6e6e3"
  night-ink-soft: "#b4b4af"
  night-rule: "#5c5c58"
  night-blue: "#9db1ff"
  night-error: "#ff8a80"
typography:
  display:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(4.25rem, 2rem + 9vw, 9rem)"
    fontWeight: 800
    lineHeight: 0.82
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 62"
    fontFeature: "'tnum'"
  headline:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(1.5rem, 1.1rem + 1.4vw, 2.25rem)"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "0"
    fontVariation: "'wdth' 80"
  wordmark:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(1.4rem, 1rem + 1.4vw, 1.9rem)"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.01em"
    fontVariation: "'wdth' 75"
  title:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 800
    letterSpacing: "0.02em"
    fontVariation: "'wdth' 80"
  figure:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "clamp(1.4rem, 1.1rem + 1vw, 2rem)"
    fontWeight: 800
    lineHeight: 1.1
    fontVariation: "'wdth' 75"
    fontFeature: "'tnum'"
  body:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    fontVariation: "'wdth' 100"
    fontFeature: "'tnum'"
  data:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.2
    fontVariation: "'wdth' 85"
    fontFeature: "'tnum'"
  label:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 700
    letterSpacing: "0.04em"
    fontVariation: "'wdth' 85"
  table-head:
    fontFamily: "Archivo, Arial Narrow, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    letterSpacing: "0.06em"
    fontVariation: "'wdth' 85"
rounded:
  none: "0px"
spacing:
  xxs: "4px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  xxl: "40px"
  column-gap: "56px"
  section-end: "64px"
  gutter: "clamp(16px, 4vw, 48px)"
  measure: "1280px"
  list-measure: "40rem"
components:
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.none}"
    padding: "10px 20px"
    height: "44px"
  tab-hover:
    backgroundColor: "{colors.newsprint-raised}"
  tab-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.newsprint}"
  select:
    backgroundColor: "{colors.newsprint}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.none}"
    padding: "8px 36px 8px 12px"
    height: "44px"
  select-hover:
    backgroundColor: "{colors.newsprint-raised}"
  text-button:
    backgroundColor: "transparent"
    textColor: "{colors.process-blue}"
    rounded: "{rounded.none}"
    padding: "0"
    height: "44px"
  text-button-hover:
    textColor: "{colors.ink}"
  agate-head-cell:
    textColor: "{colors.ink}"
    typography: "{typography.table-head}"
    padding: "8px 12px 6px 0"
  agate-cell:
    textColor: "{colors.ink}"
    typography: "{typography.data}"
    padding: "5px 16px 5px 0"
  agate-row-hover:
    backgroundColor: "{colors.newsprint-raised}"
  agate-row-latest:
    textColor: "{colors.process-blue}"
  error-message:
    textColor: "{colors.error-red}"
    rounded: "{rounded.none}"
    padding: "10px 12px"
---

# Design System: Ontario Sunshine List

## Overview

**Creative North Star: "The Agate Column"**

The list is presented the way Ontarians have always met it: in the newspaper's agate tables. A newsprint-grey page, pure ink, one process-blue spot, a single condensed grotesque, square corners and thin rules. Everything is dense, exact and columnar; figures are tabular and set hard against the right edge of their column so a reader can run a finger down them.

Hierarchy comes from width and weight of one typeface, and from the weight of rules, never from boxes, cards, shadows or tints. One figure owns the first viewport (the latest year's people count, at display scale in the spot colour), and the signature chart draws each year as a printed column of ruled agate lines whose height is the length of that year's list. The page reads as a printed record you can trust, credited to Ontario, not as a civic dashboard.

Dark mode is the same page printed in reverse: the paper goes near-black, ink goes newsprint, and the spot lightens to stay legible. Every role swaps through the same custom properties.

**Key Characteristics:**
- One self-hosted variable face (Archivo, width axis 62% to 125%) for display, labels and data.
- Tabular numerals everywhere; figures right-aligned, bold, nowrap.
- Zero radius. 1px rules between rows, 2px ink rules under masthead and section heads.
- Selected states are printed marks: filled with ink.
- One spot colour, process blue, for the latest year, links-as-actions and text selection.
- Flat. No shadows, no gradients, no tinted panels.

## Colors

Newsprint and ink with a single process-blue spot; grey carries data and rules, never decoration.

### Primary
- **Process Blue** (`process-blue`): the one spot colour. The latest year everywhere it appears (the headline figure, the latest column and its label in the chart, the latest row in the years table), the text-button actions, link hover, the focus ring and `::selection`. In dark mode it becomes **Night Blue** (`night-blue`).
- **Spot Ink** (`spot-ink`): text on a process-blue fill (text selection only).

### Neutral
- **Newsprint** (`newsprint`): the page ground. Grey, not cream.
- **Newsprint Raised** (`newsprint-raised`): the only tonal step; hover rows, tab hover and select hover. Not a surface for containers.
- **Ink** (`ink`): all primary text, every 2px and 1px structural rule, the selected-tab fill and the ink columns in the chart.
- **Ink Soft** (`ink-soft`): secondary data only: rank numbers, employer names, disabled select text (9.9:1 on newsprint).
- **Rule Grey** (`rule-grey`): the thin rules between table rows, the divider between lead facts, the status dot while checking, the loading square, the scrollbar.
- **Night Paper / Night Paper Raised / Night Ink / Night Ink Soft / Night Rule** (`night-*`): the reversed dark-mode equivalents of the five roles above, swapped under `prefers-color-scheme: dark`.

### Semantic
- **Error Red** (`error-red`, dark: `night-error`): error message text and its 1px outline, and the status dot and label on a failed health check.

### Named Rules
**The One Spot Rule.** Process blue marks the latest year and the reader's own action (selection, focus, the text-button actions). It is never a fill for panels, never a second chart series, never decoration.

**The Grey Is Data Rule.** Grey appears only as data (secondary columns, rules between rows, chart rules). No grey backgrounds, captions-as-decoration or muted ornament.

## Typography

**Display Font:** Archivo (variable, self-hosted, with Arial Narrow, system-ui, sans-serif fallback)
**Body Font:** Archivo at normal width
**Label/Mono Font:** Archivo condensed; no second family

**Character:** One grotesque family stretched and compressed through its width axis: very condensed and heavy for the agate figure, mid-condensed for labels and data, normal width for prose.

### Hierarchy
- **Display** (800, `typography.display`, width 62%): the latest year's people count only. One per page.
- **Headline** (800, `typography.headline`, width 80%): panel headings on the list tabs; the lead sentence under the display figure uses 700 at width 90%, max 22ch, balanced.
- **Wordmark** (800, uppercase, width 75%): the masthead title.
- **Title** (800, 1.25rem, uppercase, width 80%): block heads over the overview tables.
- **Figure** (800, width 75%): supporting facts in the lead.
- **Body** (400, 1rem/1.5, width 100%): prose, masthead source line, colophon at 0.875rem.
- **Data** (0.9375rem/1.2, width 85%): agate table cells; figures and names bold (700), employers and ranks regular in ink soft.
- **Label** (700, uppercase, 0.04em tracking, width 85%): tabs, status, chart caption, form labels (0.8rem).
- **Table head** (700, 0.75rem, uppercase, 0.06em tracking): column headings.

### Named Rules
**The One Family Rule.** Every role is Archivo; contrast comes from the width axis and weight, not a second face.

**The Tabular Rule.** `font-variant-numeric: tabular-nums` is set on the body and never turned off; every figure is right-aligned and `nowrap` in its column.

## Layout

All page bands share one centred measure (`spacing.measure`) and one side gutter (`spacing.gutter`). The masthead, tab bar, main and colophon are full-bleed bands separated by ink rules, with content inside the measure.

The overview lead is a 5fr / 7fr grid (display figure and facts left, year columns right, bottom-aligned); the digest below is 7fr / 5fr (highest paid, most listed titles). Column gaps are 56px; vertical rhythm steps 4 / 8 / 12 / 16 / 24 / 32 / 40 / 64px. The list tabs are one column wide: the years and titles panels hold `spacing.list-measure`; the salaries panel fits its widest row (min 40rem, max 100%) so heading rule, controls, chart and table share one right edge.

At 900px and below the lead and digest collapse to one column. At 600px and below the masthead stacks, the tab bar loses its gutter and its tabs compress to width 72% and flex to fill, and employer moves from its own column into the name cell so the salary keeps its column. Wide tables scroll inside their wrapper, never the page.

## Elevation & Depth

Completely flat. There are no shadows anywhere. Depth and grouping come from rules: a 2px ink rule closes the masthead, every panel head, block head, the lead and opens the colophon; a 1px ink rule sits under the tab bar and table headers; 1px rule-grey separates rows. The only tonal change is `newsprint-raised` on hover. A table being reloaded fades to 0.45 opacity so stale data is not mistaken for the answer.

### Named Rules
**The Rules Not Boxes Rule.** Structure is drawn with horizontal rules of two weights (1px, 2px). No cards, no bordered panels, no shadows.

## Shapes

Square everything (`rounded.none`): tabs, selects, the status dot (an 8px square), the loading indicator (a square), error boxes and chart columns. Borders are 1px (controls, row rules, tab dividers, errors) or 2px (section rules). The focus ring is a 2px process-blue outline offset 2px (inset -4px and newsprint-coloured on the selected ink tab).

## Components

### Tabs
Printed marks on a ruled bar.
- **Shape:** square, 44px minimum height, separated by 1px vertical ink rules.
- **Default:** transparent, ink label type, uppercase.
- **Hover:** newsprint-raised fill.
- **Selected:** filled ink with newsprint text.
- **Mobile:** tabs flex to fill the width, compressed to width 72%, outer rules removed.

### Text Buttons
Actions that look like what they are: underlined process-blue text (700, 0.9rem, 1px underline offset 0.2em), 44px touch height, no box. Hover turns them ink. Used for "All top salaries" style jumps between tabs.

### Inputs / Fields
- **Style:** native select restyled square, 1px ink border, newsprint fill, body-size 600 value, a drawn 12x8 chevron in ink (light chevron in dark mode), 44px minimum height.
- **Label:** uppercase label type stacked 4px above the control.
- **Hover:** newsprint-raised fill.
- **Disabled:** ink-soft text, rule-grey border, progress cursor.

### Agate Tables
Dense rows, thin rules, figures hard to the right edge.
- Header cells: table-head type over a 1px ink rule.
- Body cells: data type, 5px vertical padding, 1px rule-grey under each row; numeric cells right-aligned, bold, nowrap; rank 3ch wide in ink soft; names bold; employers ink soft.
- Hover row: newsprint-raised.
- Latest-year row: process blue, bold.

### Status and Messages
- **Health status:** uppercase label with an 8px square dot: rule grey while checking, ink when ok, error red on failure.
- **Loading:** a small rule-grey square that blinks in two steps (only when motion is allowed).
- **Error:** error-red text in a square 1px error-red outline, padded 10px 12px.

### Year Columns (signature)
An inline SVG drawn at real pixel size so its rules stay 1px. One column per year; each is filled with a 4x3 pattern of 1px horizontal lines (ink, or process blue for the latest year), capped with a solid 2px head like the rule over a column of type, standing on a 1px ink baseline. Year labels are two-digit with an apostrophe ('96) when columns are wide enough, otherwise every few full years counted back from the latest. The column under the pointer or keyboard focus fills solid; a readout in the figcaption follows it. On first draw, when motion is allowed, columns print upward from the baseline one after another (700ms, `cubic-bezier(0.16, 1, 0.3, 1)`, staggered across 600ms).

## Do's and Don'ts

### Do:
- **Do** set every figure in tabular numerals, right-aligned, bold and nowrap.
- **Do** mark selection with a solid ink fill and the latest year with process blue.
- **Do** separate sections with a 2px ink rule and rows with a 1px rule-grey rule.
- **Do** get hierarchy from Archivo's width axis and weight (display at width 62%, labels and data at 85%, prose at 100%).
- **Do** keep every interactive control at least 44px tall.
- **Do** route every colour through the custom properties so dark mode stays a single swap.

### Don't:
- **Don't** add a second accent colour or use process blue as a fill for panels or a decorative series.
- **Don't** use grey for decoration; grey is data and rules only.
- **Don't** round corners, add shadows, or wrap content in cards or tinted boxes.
- **Don't** introduce a second typeface or load fonts from a CDN; the one self-hosted Archivo file covers every role.
- **Don't** build KPI tiles or a line chart for growth; the year columns are the chart.
