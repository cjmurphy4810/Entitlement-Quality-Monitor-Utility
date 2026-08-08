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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_dashboard_controller_reuses_persona_endpoint_history_and_repair_refresh():
    """My Findings must configure the shared controller and refresh it after a repair."""
    result = _run_dashboard_runtime(r"""
const requests = [];
const payload = makePayload({}, 1);
payload.rows = [{
  violationId: 'VIO-100', userName: 'Casey Example', ruleId: 'ENT-Q-01',
  severity: 'High', status: 'Open', targetType: 'entitlement', targetId: 'ENT-1',
  detectedAt: '2026-08-07T00:00:00+00:00', repairable: true,
  detailHref: '/ctadmin/findings/VIO-100?origin=%2Fctadmin%2Fmy-findings',
}];
payload.pagination.total = 1; payload.pagination.totalPages = 1;
const fetchImpl = async url => {
  requests.push(url);
  return { ok: true, json: async () => payload };
};
const opened = [];
window.ctadminRepairDrawer = { open: (id, trigger) => opened.push([id, trigger.textContent]) };
const controller = new window.DashboardController(root, payload, {
  fetchImpl, history, location,
  endpoint: '/ctadmin/api/my-findings', pagePath: '/ctadmin/my-findings',
  includeAll: true, showRepairActions: true,
});
await controller.toggleFilter('severity', 'high');
const row = selectors['#findings-results'].children[0];
const repairButton = row.children[row.children.length - 1].children[0];
repairButton.listeners.click();
await controller.refresh();
process.stdout.write(JSON.stringify({ requests, pushed, columns: row.children.length, opened }));
""")

    assert result == {
        "requests": [
            "/ctadmin/api/my-findings?severity=high&page=1&pageSize=50&include_all=true",
            "/ctadmin/api/my-findings?severity=high&page=1&pageSize=50&include_all=true",
        ],
        "pushed": [
            "/ctadmin/my-findings?severity=high&page=1&pageSize=50&include_all=true",
            "/ctadmin/my-findings?severity=high&page=1&pageSize=50&include_all=true",
        ],
        "columns": 8,
        "opened": [["VIO-100", "Repair"]],
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_repair_drawer_traps_focus_closes_with_escape_and_preserves_invalid_input():
    """Keyboard containment and validation-state preservation are required dialog behavior."""
    dashboard_path = Path("src/eqm/ctadmin/static/dashboard.js").resolve()
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = [];
    this.listeners = {}; this.textContent = ''; this.value = ''; this.checked = false;
    this.hidden = false; this.disabled = false; this.dataset = {}; this.name = '';
    this.type = ''; this.focusCount = 0; this.className = '';
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { document.activeElement = this; this.focusCount += 1; }
  querySelectorAll(selector) {
    const result = [];
    const visit = node => {
      const named = selector === '[name]' && node.name;
      const focusable = selector.includes('button') && ['BUTTON','INPUT','TEXTAREA','SELECT'].includes(node.tagName) && !node.disabled && !node.hidden;
      if (named || focusable) result.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit); return result;
  }
}

const nodes = {};
[
  '#repair-drawer', '#repair-drawer-backdrop', '#repair-drawer-close', '#repair-cancel',
  '#repair-form', '#repair-fields', '#repair-drawer-loading', '#repair-drawer-error',
  '#repair-drawer-content', '#repair-outcome', '#repair-preview-id', '#repair-preview-reason',
  '#repair-preview-evidence', '#repair-confirm',
].forEach(key => nodes[key] = new Element(key.includes('form') ? 'form' : key.includes('confirm') || key.includes('close') || key.includes('cancel') ? 'button' : 'div'));
nodes['#repair-drawer'].dataset.csrfToken = 'csrf-value';
nodes['#repair-drawer'].append(nodes['#repair-drawer-close'], nodes['#repair-fields'], nodes['#repair-cancel'], nodes['#repair-confirm']);
const document = {
  activeElement: null,
  createElement: tag => new Element(tag),
  querySelector: selector => nodes[selector] || null,
  querySelectorAll: () => [],
  addEventListener() {},
};
const window = { window: null, document, addEventListener() {}, location: { reload() {} } };
window.window = window;
const context = { window, document, console, URLSearchParams, AbortController, Date, encodeURIComponent, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);

const trigger = new Element('button');
const calls = [];
const responses = [
  { ok: true, status: 200, json: async () => ({
    violationId: 'VIO-100', ruleId: 'ENT-Q-01', ruleName: 'PBL completeness',
    kind: 'pbl_textarea', reason: 'Too short', evidence: { pbl_description: 'bad' },
    fields: [{ name: 'pbl_description', type: 'textarea', label: 'New PBL description', value: 'starter', required: true }],
    submission: { pbl_description: 'starter' }, confirmLabel: 'Confirm repair',
  }) },
  { ok: false, status: 422, json: async () => ({ type: 'validation_error', detail: 'Description is still too short.' }) },
];
const fetchImpl = async (url, options = {}) => { calls.push({ url, options }); return responses.shift(); };

(async () => {
  const controller = new window.RepairDrawer(document, { fetchImpl });
  await controller.open('VIO-100', trigger);
  const field = nodes['#repair-fields'].querySelectorAll('[name]')[0];
  field.value = 'operator input survives';
  const focusables = nodes['#repair-drawer'].querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])');
  focusables[focusables.length - 1].focus();
  let tabPrevented = false;
  nodes['#repair-drawer'].listeners.keydown({ key: 'Tab', shiftKey: false, preventDefault() { tabPrevented = true; } });
  const wrappedToFirst = document.activeElement === focusables[0];
  await nodes['#repair-form'].listeners.submit({ preventDefault() {} });
  const valueAfterFailure = field.value;
  const disabledAfterFailure = nodes['#repair-confirm'].disabled;
  nodes['#repair-drawer'].listeners.keydown({ key: 'Escape', preventDefault() {} });
  process.stdout.write(JSON.stringify({
    openHidden: false,
    tabPrevented,
    wrappedToFirst,
    valueAfterFailure,
    disabledAfterFailure,
    error: nodes['#repair-drawer-error'].textContent,
    closed: nodes['#repair-drawer'].hidden && nodes['#repair-drawer'].attributes['aria-hidden'] === 'true',
    restoredFocus: trigger.focusCount === 1,
    postCsrf: calls[1].options.headers['X-CSRF-Token'],
  }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-", str(dashboard_path)],
        input=harness,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "openHidden": False,
        "tabPrevented": True,
        "wrappedToFirst": True,
        "valueAfterFailure": "operator input survives",
        "disabledAfterFailure": False,
        "error": "Description is still too short.",
        "closed": True,
        "restoredFocus": True,
        "postCsrf": "csrf-value",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for browserless JS QA")
def test_repair_drawer_ignores_late_preview_and_constrains_loading_focus():
    """A stale preview must not replace or submit against the currently open finding."""
    dashboard_path = Path("src/eqm/ctadmin/static/dashboard.js").resolve()
    harness = r"""
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.attributes = {}; this.children = [];
    this.listeners = {}; this.textContent = ''; this.value = ''; this.checked = false;
    this.hidden = false; this.disabled = false; this.dataset = {}; this.name = '';
    this.type = ''; this.focusCount = 0; this.className = ''; this.parentNode = null;
    this.selected = false; this.required = false; this.multiple = false;
    this.classList = { add() {}, remove() {}, toggle() {} };
  }
  append(...nodes) { nodes.forEach(node => { node.parentNode = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { document.activeElement = this; this.focusCount += 1; }
  closest(selector) {
    let node = this;
    while (node) { if (selector === '[hidden]' && node.hidden) return node; node = node.parentNode; }
    return null;
  }
  querySelectorAll(selector) {
    const result = [];
    const visit = node => {
      const named = selector === '[name]' && node.name;
      const focusable = selector.includes('button') && ['BUTTON','INPUT','TEXTAREA','SELECT'].includes(node.tagName) && !node.disabled && !node.hidden;
      if (named || focusable) result.push(node);
      node.children.forEach(visit);
    };
    this.children.forEach(visit); return result;
  }
  get selectedOptions() { return this.children.filter(option => option.selected); }
}

const nodes = {};
[
  '#repair-drawer', '#repair-drawer-backdrop', '#repair-drawer-close', '#repair-cancel',
  '#repair-form', '#repair-fields', '#repair-drawer-loading', '#repair-drawer-error',
  '#repair-drawer-content', '#repair-outcome', '#repair-preview-id', '#repair-preview-reason',
  '#repair-preview-evidence', '#repair-confirm',
].forEach(key => nodes[key] = new Element(key.includes('form') ? 'form' : key.includes('confirm') || key.includes('close') || key.includes('cancel') ? 'button' : 'div'));
nodes['#repair-drawer'].dataset.csrfToken = 'csrf-value';
nodes['#repair-form'].append(nodes['#repair-fields'], nodes['#repair-cancel'], nodes['#repair-confirm']);
nodes['#repair-drawer-content'].append(nodes['#repair-form']);
nodes['#repair-drawer'].append(nodes['#repair-drawer-close'], nodes['#repair-drawer-loading'], nodes['#repair-drawer-error'], nodes['#repair-drawer-content'], nodes['#repair-outcome']);
const document = {
  activeElement: null,
  createElement: tag => new Element(tag),
  querySelector: selector => nodes[selector] || null,
  querySelectorAll: () => [],
  addEventListener() {},
};
const window = { window: null, document, addEventListener() {}, location: { reload() {} }, setTimeout };
window.window = window;
const context = { window, document, console, URLSearchParams, AbortController, Date, encodeURIComponent, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), context);

let resolveA; let resolveB;
const calls = [];
const fetchImpl = (url, options = {}) => {
  calls.push({ url, options });
  if (options.method === 'POST') return Promise.resolve({ ok: true, status: 200, json: async () => ({
    violationId: 'B', cleared: true, summary: 'Linked B to RES-1.', changes: [],
  }) });
  if (url.includes('/A/')) return new Promise(resolve => { resolveA = resolve; });
  if (url.includes('/B/')) return new Promise(resolve => { resolveB = resolve; });
  if (url.includes('/C/')) return Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: 'Finding changed.' }) });
  throw new Error(`Unexpected request ${url}`);
};
const response = payload => ({ ok: true, status: 200, json: async () => payload });
const previewA = {
  violationId: 'A', ruleId: 'ENT-Q-01', ruleName: 'PBL completeness', kind: 'pbl_textarea',
  reason: 'A reason', evidence: {}, fields: [{ name: 'pbl_description', type: 'textarea', label: 'Description', value: 'A', required: true }],
  submission: { pbl_description: 'A' }, confirmLabel: 'Confirm repair',
};
const previewB = {
  violationId: 'B', ruleId: 'CMDB-01', ruleName: 'Orphan entitlement', kind: 'resource_select',
  reason: 'B reason', evidence: {}, fields: [{ name: 'resource_id', type: 'select', label: 'Resource', required: true,
    options: [{ value: 'RES-1', label: 'Ledger API · RES-1' }] }],
  submission: { resource_id: '' }, confirmLabel: 'Confirm repair',
};

(async () => {
  const controller = new window.RepairDrawer(document, { fetchImpl, onSuccess: async () => {} });
  const triggerA = new Element('button'); const triggerB = new Element('button');
  const openA = controller.open('A', triggerA);
  const loadingFocusables = controller.focusableElements();
  nodes['#repair-drawer-close'].focus();
  let tabPrevented = false; let shiftTabPrevented = false;
  nodes['#repair-drawer'].listeners.keydown({ key: 'Tab', shiftKey: false, preventDefault() { tabPrevented = true; } });
  nodes['#repair-drawer'].listeners.keydown({ key: 'Tab', shiftKey: true, preventDefault() { shiftTabPrevented = true; } });
  controller.close();
  const openB = controller.open('B', triggerB);
  resolveB(response(previewB));
  await openB;
  const select = nodes['#repair-fields'].querySelectorAll('[name]')[0];
  const placeholder = select.children[0];
  select.value = 'RES-1';
  resolveA(response(previewA));
  await openA;
  await nodes['#repair-form'].listeners.submit({ preventDefault() {} });
  const action = calls.find(call => call.options.method === 'POST');
  const previewId = nodes['#repair-preview-id'].textContent;
  const currentFinding = controller.findingId;
  await controller.open('C', new Element('button'));
  const errorFocusables = controller.focusableElements();
  process.stdout.write(JSON.stringify({
    loadingFocusableCount: loadingFocusables.length,
    loadingFocusableIsClose: loadingFocusables[0] === nodes['#repair-drawer-close'],
    tabPrevented, shiftTabPrevented,
    errorFocusableCount: errorFocusables.length,
    errorFocusableIsClose: errorFocusables[0] === nodes['#repair-drawer-close'],
    previewId,
    currentFinding,
    actionUrl: action.url,
    actionBody: JSON.parse(action.options.body),
    placeholderValue: placeholder.value,
    placeholderSelected: placeholder.selected,
    placeholderDisabled: placeholder.disabled,
  }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run(
        ["node", "-", str(dashboard_path)],
        input=harness,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "loadingFocusableCount": 1,
        "loadingFocusableIsClose": True,
        "tabPrevented": True,
        "shiftTabPrevented": True,
        "errorFocusableCount": 1,
        "errorFocusableIsClose": True,
        "previewId": "B / CMDB-01",
        "currentFinding": "B",
        "actionUrl": "/ctadmin/actions/findings/B/repair",
        "actionBody": {"resource_id": "RES-1"},
        "placeholderValue": "",
        "placeholderSelected": True,
        "placeholderDisabled": True,
    }
