import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_dashboard_javascript_assets_are_served_as_external_scripts(app_client):
    """Renaming, omitting, or returning HTML for either script prevents dashboard startup."""
    client, _ = app_client

    for asset in ["charts.js", "dashboard.js"]:
        response = client.get(f"/ctadmin/static/{asset}")

        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_chart_assets_render_accessible_interactive_svg_and_safe_zero_state():
    """Dropping SVG semantics, keyboard activation, or zero guards makes charts unusable."""
    charts_path = Path("src/eqm/ctadmin/static/charts.js").resolve()
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.attributes = {};
    this.children = [];
    this.listeners = {};
    this.classList = { toggle: (name, value) => this.attributes[`class:${name}`] = value };
    this.textContent = '';
  }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll(selector) {
    const found = [];
    const visit = node => {
      if (selector === '[role="button"]' && node.attributes.role === 'button') found.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit);
    return found;
  }
}

const document = {
  createElement: tag => new Element(tag),
  createElementNS: (_namespace, tag) => new Element(tag),
};
const context = { window: {}, document, console };
context.window.window = context.window;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);

const activated = [];
const bar = new Element('div');
context.window.renderBarChart(bar, [
  { key: 'high', label: 'High', count: 12 },
  { key: 'low', label: 'Low', count: 3 },
], { dimension: 'severity', selected: new Set(['high']), onSelect: (...args) => activated.push(args) });
const bars = bar.querySelectorAll('[role="button"]');
bars[0].listeners.keydown({ key: 'Enter', preventDefault() {} });

const zero = new Element('div');
context.window.renderDonutChart(zero, [
  { key: 'withFindings', label: 'With findings', count: 0 },
  { key: 'withoutFindings', label: 'Without findings', count: 0 },
], { dimension: 'coverage', selected: new Set() });
const coverageButtons = zero.querySelectorAll('[role="button"]');
const coverageSegments = zero.children[0].children.filter(child => child.tagName === 'g');

const allAttributes = node => [
  ...Object.values(node.attributes),
  ...node.children.flatMap(allAttributes),
];
process.stdout.write(JSON.stringify({
  barCount: bars.length,
  barRootRole: bar.children[0].attributes.role,
  aria: bars[0].attributes['aria-label'],
  tabIndex: bars[0].attributes.tabindex,
  dimension: bars[0].attributes['data-filter-dimension'],
  key: bars[0].attributes['data-filter-key'],
  selected: bars[0].attributes['aria-pressed'],
  title: bars[0].children.some(child => child.tagName === 'title'),
  activated,
  coverageRootRole: zero.children[0].attributes.role,
  coverageButtonCount: coverageButtons.length,
  coverageSegmentCount: coverageSegments.length,
  coverageSegmentRoles: coverageSegments.map(segment => segment.attributes.role),
  coverageLabel: coverageSegments[0]?.attributes['aria-label'],
  coverageTabIndex: coverageSegments[0]?.attributes.tabindex ?? null,
  zeroHasInvalidGeometry: allAttributes(zero).some(value => /NaN|Infinity/.test(value)),
}));
"""
    result = subprocess.run(
        ["node", "-", str(charts_path)],
        input=harness,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "barCount": 2,
        "barRootRole": "group",
        "aria": "High: 12 findings",
        "tabIndex": "0",
        "dimension": "severity",
        "key": "high",
        "selected": "true",
        "title": True,
        "activated": [["severity", "high"]],
        "coverageRootRole": "group",
        "coverageButtonCount": 0,
        "coverageSegmentCount": 2,
        "coverageSegmentRoles": ["group", "group"],
        "coverageLabel": "With findings: 0 entitlements",
        "coverageTabIndex": None,
        "zeroHasInvalidGeometry": False,
    }


DASHBOARD_BROWSERLESS_RUNTIME = r"""
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.attributes = {};
    this.children = [];
    this.listeners = {};
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this.classList = { toggle() {} };
  }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; this.textContent = ''; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

const selectors = {};
[
  '#clear-filters', '#retry-dashboard', '#previous-page', '#next-page',
  '#dashboard-search', '#finding-search', '#dashboard-error', '#kpi-total',
  '#kpi-critical', '#kpi-high', '#kpi-not-started', '#kpi-in-progress',
  '#chart-status', '#chart-severity', '#chart-target-type', '#chart-rule',
  '#chart-coverage', '#filter-summary', '#results-count', '#findings-results',
  '#page-status',
].forEach(selector => { selectors[selector] = new Element(); });

const documentListeners = {};
const document = {
  createElement: tag => new Element(tag),
  createElementNS: (_namespace, tag) => new Element(tag),
  querySelector: selector => selectors[selector] || null,
  addEventListener: (name, callback) => { documentListeners[name] = callback; },
};
const windowListeners = {};
const location = { search: '' };
const pushed = [];
const history = { pushState: (_state, _title, url) => pushed.push(url) };
const window = {
  window: null,
  addEventListener: (name, callback) => { windowListeners[name] = callback; },
  location,
  history,
  fetch: () => { throw new Error('Unexpected fetch'); },
};
window.window = window;
const context = {
  window, document, console, URLSearchParams, AbortController, Date,
  encodeURIComponent, setTimeout, clearTimeout,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);
vm.runInContext(fs.readFileSync(process.argv[3], 'utf8'), context);

function makePayload(filters = {}, page = 1) {
  return {
    kpis: {
      totalFindings: 0, criticalFindings: 0, highFindings: 0,
      notStartedFindings: 0, inProgressFindings: 0, completeFindings: 0,
    },
    coverage: { total: 0, withFindings: 0, withoutFindings: 0 },
    series: { status: [], severity: [], targetType: [], rule: [] },
    rows: [],
    filters: {
      state: [], severity: [], targetType: [], rule: [], search: '', page: 1, pageSize: 50,
      ...filters,
    },
    pagination: { page, pageSize: filters.pageSize || 50, total: 0, totalPages: 4 },
  };
}

const root = new Element('main');
"""


def _run_dashboard_runtime(scenario):
    charts_path = Path("src/eqm/ctadmin/static/charts.js").resolve()
    dashboard_path = Path("src/eqm/ctadmin/static/dashboard.js").resolve()
    result = subprocess.run(
        ["node", "-", str(charts_path), str(dashboard_path)],
        input=(
            f"{DASHBOARD_BROWSERLESS_RUNTIME}\n(async () => {{\n{scenario}\n}})()"
            ".catch(error => { console.error(error); process.exitCode = 1; });"
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_dashboard_controller_restores_filters_search_and_page_on_browser_history_pop():
    """Omitting popstate restoration leaves rendered state newer than the browser URL."""
    result = _run_dashboard_runtime(r"""
const fetched = [];
const fetchImpl = async url => {
  fetched.push(url);
  return {
    ok: true,
    json: async () => makePayload({
      state: ['complete'], severity: ['high', 'low'], search: 'retired', page: 3, pageSize: 10,
    }, 3),
  };
};
const controller = new window.DashboardController(
  root,
  makePayload({ state: ['in_progress'], search: 'current', page: 1, pageSize: 50 }),
  { fetchImpl, history, location },
);
location.search = '?state=complete&severity=high&severity=low&search=retired&page=3&pageSize=10';
if (windowListeners.popstate) await windowListeners.popstate();
process.stdout.write(JSON.stringify({
  state: [...controller.filters.get('state')],
  severity: [...controller.filters.get('severity')],
  search: controller.search,
  page: controller.page,
  pageSize: controller.pageSize,
  inputValue: selectors['#finding-search'].value,
  fetched,
  pushed,
}));
""")

    assert result == {
        "state": ["complete"],
        "severity": ["high", "low"],
        "search": "retired",
        "page": 3,
        "pageSize": 10,
        "inputValue": "retired",
        "fetched": [
            "/ctadmin/api/dashboard?state=complete&severity=high&severity=low&search=retired&page=3&pageSize=10"
        ],
        "pushed": [],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_dashboard_controller_keeps_busy_state_until_latest_request_finishes():
    """An aborted request must not mark the dashboard idle while its replacement is pending."""
    result = _run_dashboard_runtime(r"""
const requests = [];
const fetchImpl = (_url, options) => new Promise((resolve, reject) => {
  options.signal.addEventListener('abort', () => {
    const error = new Error('Superseded');
    error.name = 'AbortError';
    reject(error);
  });
  requests.push({ resolve });
});
const controller = new window.DashboardController(root, makePayload(), { fetchImpl, history, location });
const first = controller.refresh();
const second = controller.refresh();
await first;
const busyAfterAbort = root.attributes['aria-busy'];
requests[1].resolve({ ok: true, json: async () => makePayload() });
await second;
process.stdout.write(JSON.stringify({
  busyAfterAbort,
  busyAfterLatest: root.attributes['aria-busy'],
}));
""")

    assert result == {"busyAfterAbort": "true", "busyAfterLatest": "false"}
