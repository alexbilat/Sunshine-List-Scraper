// The Sunshine List page: loads salary data and shows it.
//
// The same page runs in two places (see the data-source meta tag):
// - "api": served by the live server on your PC; data comes from /api/...
// - "static": the public site built by publish_site.py; data comes from
//   pre-built JSON files next to the page, so no server is needed.
// Only the small `source` object below differs; everything else is shared.
//
// Safety rule for this whole file: the data (names, employers, job titles) is
// external text. It is only ever placed on the page with textContent or
// createElement, never innerHTML, so text such as "<img onerror=...>" is shown
// as text instead of being run as HTML.
'use strict';

// --- Fetching JSON ------------------------------------------------------------

// An error a person can understand, plus the HTTP status for callers that care.
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// GET one path and return its parsed JSON.
// Relative URLs always go to the server that served this page, so the page
// needs no configuration and never talks to another site.
// URLSearchParams escapes values, so a parameter can't break the URL.
// unreachable is the message shown when no response arrives at all; it
// depends on where the data lives, so each source passes its own.
async function getJson(path, unreachable, params = {}) {
  const query = new URLSearchParams(params).toString();
  let response;
  try {
    response = await fetch(query ? `${path}?${query}` : path, {
      headers: { Accept: 'application/json' },
    });
  } catch {
    // fetch only rejects when no response arrived at all (server stopped,
    // network down). HTTP errors such as 503 still resolve normally.
    throw new ApiError(unreachable, 0);
  }
  if (response.ok) {
    return response.json();
  }
  throw new ApiError(await describeError(response), response.status);
}

// Turn an error response into one friendly sentence.
async function describeError(response) {
  if (response.status === 429) {
    // The server says how long to wait; it counts requests per minute.
    const wait = Number(response.headers.get('Retry-After')) || 60;
    return `Too many requests. Please wait ${wait} second${wait === 1 ? '' : 's'} and try again.`;
  }
  if (response.status === 503) {
    return 'The database is unavailable right now. Please try again later.';
  }
  if (response.status === 422) {
    // FastAPI lists what was wrong with each parameter, e.g.
    // {"detail": [{"loc": ["query", "limit"], "msg": "Input should be ..."}]}.
    try {
      const body = await response.json();
      const problems = (body.detail || []).map((item) => `${item.loc.at(-1)}: ${item.msg}`);
      if (problems.length) {
        return `Invalid request (${problems.join('; ')}).`;
      }
    } catch {
      // Not the JSON we expected; fall through to the generic message.
    }
    return 'Invalid request.';
  }
  return `Something went wrong (HTTP ${response.status}).`;
}

// --- Where the data comes from ------------------------------------------------
// Both sources answer the same three questions with the same JSON shapes
// (publish_site.py writes the files with the API's own response models).
// Everything else that differs between the two modes also lives here, so the
// rest of the file never needs to ask which mode it is in.

const SERVER_UNREACHABLE = 'Could not reach the server. Is it running?';
const liveSource = {
  years: () => getJson('/api/years', SERVER_UNREACHABLE),
  titles: (limit) => getJson('/api/titles/top', SERVER_UNREACHABLE, { limit }),
  topSalaries: (year, limit) =>
    getJson('/api/salaries/top', SERVER_UNREACHABLE, { year, limit }),
  async status() {
    await getJson('/api/health', SERVER_UNREACHABLE);
    return 'Database connected';
  },
  // A 429 means the server is fine but this visitor asked too often.
  statusFailed: (error) => (error.status === 429 ? 'Busy' : 'Database unavailable'),
  // FastAPI's interactive /docs page exists only on the live server.
  hasApiDocs: true,
};

// The static files hold the top 100 of each list; the page shows the first
// `limit` of them, which is exactly what the API would have returned.
// Paths have no leading slash: GitHub Pages serves the site from a
// sub-folder (/<repository>/), and relative paths work wherever it lives.
const FILES_UNREACHABLE =
  'Could not load the data. Check your internet connection and try again.';
const staticSource = {
  years: () => getJson('data/years.json', FILES_UNREACHABLE),
  titles: async (limit) =>
    (await getJson('data/titles.json', FILES_UNREACHABLE)).slice(0, Number(limit)),
  topSalaries: async (year, limit) =>
    (await getJson(`data/salaries/${encodeURIComponent(year)}.json`, FILES_UNREACHABLE))
      .slice(0, Number(limit)),
  async status() {
    const meta = await getJson('data/meta.json', FILES_UNREACHABLE);
    const date = new Date(meta.generated_at).toLocaleDateString('en-CA', {
      year: 'numeric', month: 'long', day: 'numeric',
    });
    return `Data updated ${date}`;
  },
  statusFailed: () => 'Data unavailable',
  hasApiDocs: false,
};

const source =
  document.querySelector('meta[name="data-source"]')?.content === 'static'
    ? staticSource : liveSource;

// --- Formatting ---------------------------------------------------------------

const wholeNumber = new Intl.NumberFormat('en-CA');

// Non-ASCII characters are written as escapes so this file reads the same
// whatever character set a browser assumes for it.
const ELLIPSIS = '\u2026';

// Format exact integer cents as "$123,456.78".
// The API sends integer cents so no precision is lost. Splitting into whole
// dollars and leftover cents with integer arithmetic keeps it exact here too;
// dividing into a float and rounding could show the wrong last digit.
function formatCents(cents) {
  if (cents === null || cents === undefined) {
    return '\u2014'; // an em dash: "no value"
  }
  const dollars = Math.floor(cents / 100);
  const remainder = String(cents % 100).padStart(2, '0');
  return `$${wholeNumber.format(dollars)}.${remainder}`;
}

// --- Small DOM helpers --------------------------------------------------------

const $ = (id) => document.getElementById(id);

// Build a table row from plain values. textContent makes every value inert text.
function tableRow(cells) {
  const row = document.createElement('tr');
  for (const { text, numeric } of cells) {
    const cell = document.createElement('td');
    cell.textContent = text;
    if (numeric) {
      cell.className = 'num';
    }
    row.append(cell);
  }
  return row;
}

// Replace a table's rows, and hide the table when there is nothing to show.
function fillTable(table, rows) {
  table.tBodies[0].replaceChildren(...rows);
  table.hidden = rows.length === 0;
}

// Show a status line. kind is '' (neutral), 'loading' or 'error'.
function showMessage(element, text, kind = '') {
  element.textContent = text;
  element.className = `message ${kind}`.trim();
}

// Run a request while its button is disabled. Stops double clicks from sending
// the same request twice and makes it obvious that something is happening.
async function whileBusy(button, work) {
  if (button) button.disabled = true;
  try {
    await work();
  } finally {
    if (button) button.disabled = false;
  }
}

// --- Status indicator ---------------------------------------------------------
// Live: is the database reachable? Static: when was the data published?

async function checkHealth() {
  const box = $('health');
  try {
    $('health-text').textContent = await source.status();
    box.dataset.state = 'ok';
  } catch (error) {
    box.dataset.state = 'error';
    $('health-text').textContent = source.statusFailed(error);
  }
}

// --- Years (used by two panels) -----------------------------------------------

// The years list feeds both the year picker and the overview panel, so it is
// requested once and shared. Keeping the promise means a second caller waits
// for the same request instead of starting another one.
let yearsPromise = null;
function loadYears() {
  if (!yearsPromise) {
    yearsPromise = source.years().catch((error) => {
      yearsPromise = null; // allow a retry later
      throw error;
    });
  }
  return yearsPromise;
}

// --- Panel: top salaries ------------------------------------------------------

async function setUpSalaries() {
  const select = $('salaries-year');
  const message = $('salaries-message');
  try {
    const years = await loadYears();
    // Newest first, and only years that actually have people listed.
    const available = years.filter((year) => year.people > 0).map((year) => year.year)
      .sort((a, b) => b - a);
    if (available.length === 0) {
      select.replaceChildren(new Option('No data yet', ''));
      showMessage(message, 'The database has no salary records yet. Run the scraper first.');
      return;
    }
    select.replaceChildren(...available.map((year) => new Option(String(year), String(year))));
    select.disabled = false;
    $('salaries-submit').disabled = false;
    await showTopSalaries();
  } catch (error) {
    select.replaceChildren(new Option('Unavailable', ''));
    showMessage(message, error.message, 'error');
  }
}

async function showTopSalaries() {
  const year = $('salaries-year').value;
  const limit = $('salaries-limit').value;
  const message = $('salaries-message');
  const table = $('salaries-table');
  if (!year) return;
  showMessage(message, `Loading salaries for ${year}${ELLIPSIS}`, 'loading');
  await whileBusy($('salaries-submit'), async () => {
    try {
      const salaries = await source.topSalaries(year, limit);
      fillTable(table, salaries.map((salary, index) => tableRow([
        { text: String(index + 1), numeric: true },
        { text: salary.name },
        { text: salary.employer },
        { text: formatCents(salary.salary_cents), numeric: true },
      ])));
      showMessage(message, salaries.length
        ? `Top ${salaries.length} salaries disclosed for ${year}.`
        : `No records for ${year}.`);
    } catch (error) {
      fillTable(table, []);
      showMessage(message, error.message, 'error');
    }
  });
}

// --- Panel: years overview ----------------------------------------------------

async function showYears() {
  const message = $('years-message');
  showMessage(message, `Loading yearly totals${ELLIPSIS}`, 'loading');
  try {
    const years = await loadYears();
    fillTable($('years-table'), [...years].reverse().map((year) => tableRow([
      { text: String(year.year) },
      { text: wholeNumber.format(year.people), numeric: true },
      { text: formatCents(year.average_salary_cents), numeric: true },
    ])));
    drawYearsChart(years);
    showMessage(message, years.length ? '' : 'The database has no salary records yet.');
  } catch (error) {
    showMessage(message, error.message, 'error');
  }
}

// A simple bar chart of people per year, drawn as SVG.
// Built with DOM calls rather than a chart library: the page then needs no
// third-party script, which keeps the security policy strict ("only scripts
// from this server"). Colours come from styles.css so dark mode works.
function drawYearsChart(years) {
  const figure = $('years-chart');
  const body = $('years-chart-body');
  if (years.length === 0) {
    figure.hidden = true;
    return;
  }
  const NS = 'http://www.w3.org/2000/svg';
  const make = (name, attributes) => {
    const element = document.createElementNS(NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      element.setAttribute(key, String(value));
    }
    return element;
  };

  // Drawing units, not pixels: the viewBox scales the whole chart to fit the
  // available width, so it works on a phone and on a wide screen.
  const width = 720;
  const height = 260;
  const top = 12;
  const bottom = 28; // room for year labels
  const left = 8;
  const plotHeight = height - top - bottom;
  const slot = (width - left * 2) / years.length;
  const barWidth = Math.max(2, slot * 0.7);
  const maxPeople = Math.max(...years.map((year) => year.people), 1);
  // With many years, label only every few so the labels don't overlap.
  const labelEvery = Math.ceil(years.length / 12);

  const svg = make('svg', {
    viewBox: `0 0 ${width} ${height}`,
    role: 'img',
    'aria-label': 'Bar chart of people listed per year. The table below has the exact numbers.',
  });
  svg.append(make('line', {
    class: 'axis', x1: left, x2: width - left, y1: top + plotHeight, y2: top + plotHeight,
  }));
  years.forEach((year, index) => {
    const barHeight = (year.people / maxPeople) * plotHeight;
    const x = left + index * slot + (slot - barWidth) / 2;
    const bar = make('rect', {
      class: 'bar', x, y: top + plotHeight - barHeight, width: barWidth, height: barHeight, rx: 2,
    });
    // <title> gives a hover tooltip with the exact value.
    const tooltip = make('title', {});
    tooltip.textContent = `${year.year}: ${wholeNumber.format(year.people)} people`;
    bar.append(tooltip);
    svg.append(bar);
    if (index % labelEvery === 0 || index === years.length - 1) {
      const label = make('text', {
        class: 'label', x: left + index * slot + slot / 2, y: height - 8, 'text-anchor': 'middle',
      });
      label.textContent = String(year.year);
      svg.append(label);
    }
  });
  body.replaceChildren(svg);
  figure.hidden = false;
}

// --- Panel: common job titles -------------------------------------------------

async function showTitles() {
  const limit = $('titles-limit').value;
  const message = $('titles-message');
  const table = $('titles-table');
  showMessage(message, `Loading job titles${ELLIPSIS}`, 'loading');
  await whileBusy($('titles-submit'), async () => {
    try {
      const titles = await source.titles(limit);
      fillTable(table, titles.map((title, index) => tableRow([
        { text: String(index + 1), numeric: true },
        { text: title.job_title },
        { text: wholeNumber.format(title.appearances), numeric: true },
      ])));
      showMessage(message, titles.length ? '' : 'No job titles recorded yet.');
    } catch (error) {
      fillTable(table, []);
      showMessage(message, error.message, 'error');
    }
  });
}

// --- Tabs ---------------------------------------------------------------------

// Each panel loads its data the first time it is opened, not on page load, so
// visitors who only want one view don't spend requests on the others.
const panelLoaders = {
  'panel-years': showYears,
  'panel-titles': showTitles,
};
const loadedPanels = new Set();

function selectTab(tab) {
  for (const other of document.querySelectorAll('[role="tab"]')) {
    const selected = other === tab;
    other.setAttribute('aria-selected', String(selected));
    other.tabIndex = selected ? 0 : -1;
    $(other.getAttribute('aria-controls')).hidden = !selected;
  }
  const panelId = tab.getAttribute('aria-controls');
  if (panelLoaders[panelId] && !loadedPanels.has(panelId)) {
    loadedPanels.add(panelId);
    panelLoaders[panelId]();
  }
}

function setUpTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, index) => {
    tab.tabIndex = index === 0 ? 0 : -1;
    tab.addEventListener('click', () => selectTab(tab));
    // Arrow keys move between tabs, as screen-reader users expect.
    tab.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (step) {
        const next = tabs[(index + step + tabs.length) % tabs.length];
        next.focus();
        selectTab(next);
      }
    });
  });
}

// --- Start --------------------------------------------------------------------

function start() {
  $('api-docs-link').hidden = !source.hasApiDocs;
  setUpTabs();
  // preventDefault stops the browser's own form submission (a page reload);
  // the forms only exist so pressing Enter works.
  $('salaries-form').addEventListener('submit', (event) => {
    event.preventDefault();
    showTopSalaries();
  });
  $('titles-form').addEventListener('submit', (event) => {
    event.preventDefault();
    showTitles();
  });
  checkHealth();
  setUpSalaries();
}

start();
