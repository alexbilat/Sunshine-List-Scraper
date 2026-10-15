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
const EM_DASH = '\u2014';

// Format exact integer cents as "$123,456.78".
// The API sends integer cents so no precision is lost. Splitting into whole
// dollars and leftover cents with integer arithmetic keeps it exact here too;
// dividing into a float and rounding could show the wrong last digit.
function formatCents(cents) {
  if (cents === null || cents === undefined) {
    return EM_DASH; // "no value"
  }
  const dollars = Math.floor(cents / 100);
  const remainder = String(cents % 100).padStart(2, '0');
  return `$${wholeNumber.format(dollars)}.${remainder}`;
}

// --- Small DOM helpers --------------------------------------------------------

const $ = (id) => document.getElementById(id);

// Make an element with an optional class and text. textContent keeps it inert.
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Build a table row from cells. Each cell is { text, className } or a ready
// <td> element (for cells with more than one piece of text).
function tableRow(cells, rowClass) {
  const row = element('tr', rowClass);
  for (const cell of cells) {
    row.append(cell instanceof Node ? cell : element('td', cell.className, cell.text));
  }
  return row;
}

// One salary as a table row.
function salaryRow(salary, index) {
  return tableRow([
    { text: String(index + 1), className: 'num rank' },
    { text: salary.name, className: 'name' },
    { text: salary.employer, className: 'employer employer-col' },
    { text: formatCents(salary.salary_cents), className: 'num' },
  ]);
}

function titleRow(title, index) {
  return tableRow([
    { text: String(index + 1), className: 'num rank' },
    { text: title.job_title },
    { text: wholeNumber.format(title.appearances), className: 'num' },
  ]);
}

// Replace a table's rows, and hide the table when there is nothing to show.
function fillTable(table, rows) {
  table.tBodies[0].replaceChildren(...rows);
  table.hidden = rows.length === 0;
}

// Show a status line. kind is '' (neutral), 'loading' or 'error'.
function showMessage(target, text, kind = '') {
  target.textContent = text;
  target.className = `message ${kind}`.trim();
}

// Load rows into a table, showing progress and errors in its message line.
// Selects update the table as soon as they change, so a quick second change
// can start a new request before the first one answers. Each table remembers
// its latest request, and an older answer arriving late is ignored instead
// of overwriting the newer one.
const latestRequest = new WeakMap();
async function loadTable({ table, message, loading, fetchRows, toRow, done }) {
  const ticket = {};
  latestRequest.set(table, ticket);
  showMessage(message, loading, 'loading');
  table.setAttribute('aria-busy', 'true');
  try {
    const items = await fetchRows();
    if (latestRequest.get(table) !== ticket) return;
    fillTable(table, items.map(toRow));
    showMessage(message, done(items));
  } catch (error) {
    if (latestRequest.get(table) !== ticket) return;
    fillTable(table, []);
    showMessage(message, error.message, 'error');
  } finally {
    if (latestRequest.get(table) === ticket) table.removeAttribute('aria-busy');
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

// Only years that actually have people listed, oldest first.
const listedYears = (years) =>
  years.filter((year) => year.people > 0).sort((a, b) => a.year - b.year);

// --- The year columns chart ---------------------------------------------------
// One column per year, filled with thin ruled lines like a column of small
// newspaper type, so each column's height reads as the length of that year's
// list. Drawn as SVG with DOM calls rather than a chart library: the page
// then needs no third-party script, which keeps the security policy strict.
// Colours come from styles.css so dark mode works.

const SVG_NS = 'http://www.w3.org/2000/svg';
function svg(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

// What the readout line says about one year.
function describeYear(year) {
  return [`${year.year}: `, wholeNumber.format(year.people),
    ` people listed, average ${formatCents(year.average_salary_cents)}`];
}

function showReadout(readout, year) {
  const [before, figure, after] = describeYear(year);
  readout.replaceChildren(before, element('strong', '', figure), after);
}

// Draw (or redraw) a columns chart.
// chart: { figure, body, readout, idPrefix, onPick } and the years to show.
// The drawing is sized to the box it sits in, in real pixels, so the ruled
// lines stay one pixel thin on every screen instead of being scaled.
function drawColumns(chart, years, { animate }) {
  const { figure, body, readout, idPrefix, onPick } = chart;
  if (years.length === 0) {
    figure.hidden = true;
    return;
  }
  figure.hidden = false;

  const width = Math.max(280, Math.round(body.clientWidth));
  const height = Math.round(Math.min(320, Math.max(200, width * 0.42)));
  const labelSpace = 22;
  const plotHeight = height - labelSpace;
  const slot = width / years.length;
  const gap = Math.max(1, Math.min(6, slot * 0.22));
  const maxPeople = Math.max(...years.map((year) => year.people), 1);
  // Wide columns get every year, shortened to two digits ("\u201996") the way
  // a newspaper table would; narrow ones get every few full years. Counting
  // back from the latest year keeps the gaps even right up to the newest one.
  const shortLabels = slot >= 16;
  const labelEvery = shortLabels ? 1 : Math.ceil(44 / slot);
  const latest = years[years.length - 1];

  const root = svg('svg', {
    viewBox: `0 0 ${width} ${height}`,
    width, height,
    role: 'group',
    'aria-label': 'One column per year; taller means more people listed. '
      + 'Use the arrow keys to move between years and Enter to see that year\u2019s top salaries.',
  });

  // The two fills: ink lines and spot-colour lines, three pixels apart.
  const defs = svg('defs');
  for (const [suffix, className] of [['ink', 'agate-ink'], ['spot', 'agate-spot']]) {
    const pattern = svg('pattern', {
      id: `${idPrefix}-${suffix}`, width: 4, height: 3, patternUnits: 'userSpaceOnUse',
    });
    pattern.append(svg('rect', { class: className, width: 4, height: 1 }));
    defs.append(pattern);
  }
  root.append(defs);

  const groups = years.map((year, index) => {
    const isLatest = year === latest;
    const columnHeight = Math.max(2, (year.people / maxPeople) * (plotHeight - 4));
    const x = index * slot + gap / 2;
    const y = plotHeight - columnHeight;
    const group = svg('g', {
      class: 'year', role: 'button', tabindex: isLatest ? 0 : -1,
      'aria-label': `${describeYear(year).join('')}. Show top salaries for ${year.year}.`,
    });
    // An invisible full-height target so short early columns are easy to hit.
    group.append(svg('rect', {
      class: 'col-hit', x: index * slot, y: 0, width: slot, height: plotHeight,
    }));
    const column = svg('rect', {
      class: `col${isLatest ? ' latest' : ''}`, x, y, width: slot - gap, height: columnHeight,
      fill: `url(#${idPrefix}-${isLatest ? 'spot' : 'ink'})`,
    });
    // A solid head on each column, like the rule over a column of type.
    const cap = svg('rect', {
      class: `col-cap${isLatest ? ' latest' : ''}`, x, y, width: slot - gap, height: 2,
    });
    if (animate) {
      // Set as a style property (allowed by the policy, unlike a style
      // attribute) so the columns print one after another.
      const delay = `${Math.round(index * (600 / years.length))}ms`;
      column.style.animationDelay = delay;
      cap.style.animationDelay = delay;
    }
    group.append(column, cap);
    if ((years.length - 1 - index) % labelEvery === 0) {
      const label = svg('text', {
        class: `label${isLatest ? ' latest' : ''}`,
        x: index * slot + slot / 2, y: height - 6, 'text-anchor': 'middle',
      });
      label.textContent = shortLabels ? `\u2019${String(year.year).slice(-2)}` : String(year.year);
      group.append(label);
    }
    root.append(group);
    return group;
  });
  root.append(svg('line', { class: 'baseline', x1: 0, x2: width, y1: plotHeight, y2: plotHeight }));

  // Pointer and keyboard both move one "active" column; the readout follows.
  let active = groups.length - 1;
  const activate = (index) => {
    groups[active].classList.remove('is-active');
    active = index;
    groups[active].classList.add('is-active');
    showReadout(readout, years[active]);
  };
  const rest = () => {
    groups[active].classList.remove('is-active');
    showReadout(readout, latest);
  };
  groups.forEach((group, index) => {
    group.addEventListener('pointerenter', () => activate(index));
    group.addEventListener('focus', () => activate(index));
    group.addEventListener('click', () => onPick(years[index].year));
    group.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1, Home: -Infinity, End: Infinity }[event.key];
      if (step !== undefined) {
        event.preventDefault();
        const next = Math.min(groups.length - 1, Math.max(0, index + step));
        group.tabIndex = -1;
        groups[next].tabIndex = 0;
        groups[next].focus();
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onPick(years[index].year);
      }
    });
  });
  root.addEventListener('pointerleave', rest);
  root.addEventListener('focusout', (event) => {
    if (!root.contains(event.relatedTarget)) rest();
  });

  showReadout(readout, latest);
  body.replaceChildren(root);
  if (animate) {
    figure.classList.add('is-printing');
    // Drop the class afterwards so a redraw (window resize) doesn't replay it.
    setTimeout(() => figure.classList.remove('is-printing'), 1400);
  }
}

// Charts that have been drawn, so they can be redrawn at a new width.
const drawnCharts = [];
function showColumns(chart, years) {
  drawColumns(chart, years, { animate: true });
  drawnCharts.push({ chart, years });
}

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    for (const { chart, years } of drawnCharts) {
      // A chart in a hidden panel has no width; it is redrawn when shown.
      if (!chart.figure.closest('[hidden]')) drawColumns(chart, years, { animate: false });
    }
  }, 150);
});

// --- Panel: top salaries ------------------------------------------------------

// Filled once, when the years first arrive; later visits just show the panel.
async function setUpSalaries() {
  const select = $('salaries-year');
  const message = $('salaries-message');
  try {
    // Newest first in the picker.
    const available = listedYears(await loadYears()).map((year) => year.year).reverse();
    if (available.length === 0) {
      select.replaceChildren(new Option('No data yet', ''));
      showMessage(message, 'The database has no salary records yet. Run the scraper first.');
      return;
    }
    // A year picked from a chart before the years arrived wins.
    const wanted = pendingYear ?? available[0];
    select.replaceChildren(...available.map((year) => new Option(String(year), String(year))));
    select.value = String(wanted);
    select.disabled = false;
    showTopSalaries();
  } catch (error) {
    select.replaceChildren(new Option('Unavailable', ''));
    showMessage(message, error.message, 'error');
  }
}

function showTopSalaries() {
  const year = $('salaries-year').value;
  const limit = $('salaries-limit').value;
  if (!year) return;
  loadTable({
    table: $('salaries-table'),
    message: $('salaries-message'),
    loading: `Loading salaries for ${year}${ELLIPSIS}`,
    fetchRows: () => source.topSalaries(year, limit),
    toRow: salaryRow,
    done: (items) => (items.length
      ? `Top ${items.length} salaries disclosed for ${year}.`
      : `No records for ${year}.`),
  });
}

// Open the top salaries panel on one year (used by the chart columns).
let pendingYear = null;
function openYear(year) {
  const select = $('salaries-year');
  selectTab($('tab-salaries'));
  if (select.disabled) {
    pendingYear = year; // the picker isn't filled yet; setUpSalaries uses it
    return;
  }
  if (select.value !== String(year)) {
    select.value = String(year);
    showTopSalaries();
  }
  $('tab-salaries').focus();
}

// --- Panel: years -------------------------------------------------------------

async function showYears() {
  const message = $('years-message');
  showMessage(message, `Loading yearly totals${ELLIPSIS}`, 'loading');
  try {
    const years = listedYears(await loadYears());
    const latestYear = years.length ? years[years.length - 1].year : null;
    fillTable($('years-table'), [...years].reverse().map((year) => tableRow([
      { text: String(year.year) },
      { text: wholeNumber.format(year.people), className: 'num' },
      { text: formatCents(year.average_salary_cents), className: 'num' },
    ], year.year === latestYear ? 'latest' : '')));
    showColumns({
      figure: $('years-chart'),
      body: $('years-chart-body'),
      readout: $('years-readout'),
      idPrefix: 'years',
      onPick: openYear,
    }, years);
    showMessage(message, years.length ? '' : 'The database has no salary records yet.');
  } catch (error) {
    showMessage(message, error.message, 'error');
  }
}

// --- Panel: common job titles -------------------------------------------------

function showTitles() {
  loadTable({
    table: $('titles-table'),
    message: $('titles-message'),
    loading: `Loading job titles${ELLIPSIS}`,
    fetchRows: () => source.titles($('titles-limit').value),
    toRow: titleRow,
    done: (items) => (items.length ? '' : 'No job titles recorded yet.'),
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
  } else {
    // A chart drawn while the window was a different size is redrawn to fit.
    for (const { chart, years } of drawnCharts) {
      if ($(panelId).contains(chart.figure)) drawColumns(chart, years, { animate: false });
    }
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
  // The lists update as soon as a choice changes. preventDefault stops the
  // browser's own form submission (a page reload) if Enter is pressed.
  for (const form of [$('salaries-form'), $('titles-form')]) {
    form.addEventListener('submit', (event) => event.preventDefault());
  }
  $('salaries-year').addEventListener('change', showTopSalaries);
  $('salaries-limit').addEventListener('change', showTopSalaries);
  $('titles-limit').addEventListener('change', showTitles);
  checkHealth();
  setUpSalaries();
}

start();
