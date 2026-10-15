# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: the curious public.** Ontarians who want to see who in the public sector earns $100,000 or more, which jobs dominate the list, and how the list has grown since 1996. Casual visits, often on a phone, often arriving from a news story or a conversation.
- **Secondary: journalists and researchers.** They need accurate, citable figures and year-over-year trends, and they need to trust that the numbers match Ontario's official disclosures.
- **Secondary: portfolio reviewers.** Recruiters and engineers evaluating the project. They judge the site as evidence of the engineering behind it (exact money, incremental sync, hardened API, safe frontend).

## Product Purpose

Ontario publishes the Sunshine List as 81 separate datasets across two systems (CKAN API and CSV downloads), and the column names change from year to year. This project collects all of it, normalizes and validates it, stores it in PostgreSQL as the source of truth, and publishes one fast, searchable website. Success means anyone can answer "who earns the most, in what jobs, and how has that changed" in seconds, and every figure traces back to the official source.

## Positioning

It holds every disclosure from 1996 to the latest year in one clean dataset (about 3.27M records). Salaries are exact integer cents from parse to browser, and nothing is ever deleted: a changed salary becomes a new record. New years are picked up automatically, and the public site is a free static mirror that needs no server.

## Operating Context

- Public site: static GitHub Pages build (`publish_site.py` → `site/` → `gh-pages`), served under `/<repo>/`, so data paths stay relative. The header shows "Data updated <date>" from `meta.json`.
- Local site: the same frontend served by the read-only FastAPI app at `/`, with live DB health in the header and API docs at `/docs`.
- Data refresh is a maintainer ritual: run the scraper (incremental, about 1 minute), then publish.
- Current views: top salaries per year (top 10/25/50/100), years overview (headcount + average salary chart and table), and most common job titles across all years.

## Capabilities and Constraints

- The public site shows only pre-computed answers: the top 100 per list (`storage.repository.MAX_LIMIT`), yearly aggregates, and top titles. Any new view must be expressible as static JSON or must accept being local-only.
- Strict Content-Security-Policy: no inline scripts or styles, no third-party/CDN scripts, `img-src 'self' data:`. Data is rendered only via `textContent`/`createElement`. `app.js` stays ASCII.
- No build step: plain HTML, CSS, and JavaScript (the chart is inline SVG).
- Money is displayed from integer cents; floats are never used.
- The API is GET-only and read-only, with rate limits and query-slot caps.
- **Planned:** search by person name and by employer. How that fits the static public site (pre-built index vs. local-only) is undecided.
- Terminology: "disclosure" (one record), "the Sunshine List", "Public Sector Salary Disclosure", "employer", "job title", "salary paid", "people listed".

## Brand Commitments

- Name: "Ontario Sunshine List".
- Voice: neutral public record. State facts plainly and attribute them to Ontario's disclosures. Don't comment on whether pay is too high or too low, and don't frame individuals.
- Always credit and link the official source (Ontario Public Sector Salary Disclosure).

## Evidence on Hand

- Real dataset: about 3.27M disclosures, 1996–2025, 81 source datasets; 4,512 people listed in 1996 and 404,916 in 2025; average listed salary $121,484.94 in 1996 and $134,229.51 in 2025; most common title Registered Nurse (124,626 listings). Figures come from `README.md` and shift with each sync.
- Screenshots and charts: `assets/website.png`, `assets/chart_yearly.png`, `chart_titles.png`.
- Live site: https://alexbilat.github.io/Sunshine-List-Scraper/
- No testimonials, press coverage, or usage metrics exist; don't fabricate them.

## Product Principles

1. **The official record, faithfully.** Every number is exact and traceable to Ontario's disclosures. Accuracy outranks flourish.
2. **Neutral, not editorial.** Present the data and let readers draw conclusions; context explains, never argues.
3. **Fast answers for a casual visitor.** The common questions (top earners this year, how the list has grown, which jobs dominate) are answerable in one or two taps, including on mobile.
4. **Static-first and safe.** Features must work within the free static mirror and the strict CSP. Server-only features are explicitly local.
5. **Craft is the proof.** For reviewers, the site's reliability and precision demonstrate the engineering, so nothing on it may be sloppy or approximate.

## Accessibility & Inclusion

The audience is the general Ontario public, including mobile and assistive-technology users. Keep the existing semantic tabs/tables/ARIA live-region patterns, and target WCAG 2.2 AA. Bilingual (French) support has not been decided.
