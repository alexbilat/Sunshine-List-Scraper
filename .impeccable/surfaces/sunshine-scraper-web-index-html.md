---
version: 1
slug: "sunshine-scraper-web-index-html"
primary_target: "sunshine_scraper/web/index.html"
related_targets: ["sunshine_scraper/web/app.js","sunshine_scraper/web/styles.css"]
---

# Surface brief: public site (sunshine_scraper/web/)

Scope: the whole single-page site (local API mode and static GitHub Pages mode). Visitor mode: Operate.

Audience/job: curious Ontarians (often on phones, from a news story), journalists, portfolio reviewers. Answer "who earns the most, in what jobs, how has the list grown" in one or two taps.
Content: existing data only. Years overview (people + average salary per year), top salaries per year (10/25/50/100), most common job titles. No new features, no name search.
Constraints: strict CSP (no inline script/style, no CDN), textContent/createElement only, app.js ASCII, no build step, chart is inline SVG, money from integer cents, static data paths relative.

## Direction contract

THESIS: The list as Ontarians have always met it, in the newspaper's agate tables: dense, exact, columnar, and visibly growing every year. Refuses the KPI-card civic dashboard with a blue line chart.

OWN-WORLD: Newsprint-grey ground (#E6E6E3), pure ink (#161616), one process-blue spot (#1F3A93) for the current year and selection. Grey only as data. One condensed grotesque family for display, labels and data, uppercase bold labels. Zero radius, 1px rules, 2px ink rules for section heads; selected states are filled ink. Figures right-aligned hard to one column edge with tabular numerals.

STORY: The visitor sees how long the list is this year, how it grew from 4,512 to 404,916, then reads who earns the most and which jobs dominate, and trusts it because every figure is exact and credited to Ontario.

FIRST VIEWPORT: Ink-ruled top bar (name, data date, source). Tabs: Overview, Top salaries, Years, Job titles. Overview opens with the latest year's people-listed figure at display scale (owns the viewport) with average salary and the 1996 count beneath; to its right, one printed column per year whose height is that year's list length, latest in blue. Below: highest paid (latest year) and most listed titles as agate tables.

FORM: Agate Column, candidate 3 of 7 (seed key 3c64da6c). Signature move: the year columns, filled with ruled agate lines, so the chart reads as the printed list's length. Raises: grey only as data (Ikeda); one grotesque family (design annual); hard right-aligned figures, capacity visible (j-card); one figure owns the viewport (vertical feed); states as printed marks, zero radius, 1px rules (centre rail).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
