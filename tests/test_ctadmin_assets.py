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

const allAttributes = node => [
  ...Object.values(node.attributes),
  ...node.children.flatMap(allAttributes),
];
process.stdout.write(JSON.stringify({
  barCount: bars.length,
  aria: bars[0].attributes['aria-label'],
  tabIndex: bars[0].attributes.tabindex,
  dimension: bars[0].attributes['data-filter-dimension'],
  key: bars[0].attributes['data-filter-key'],
  selected: bars[0].attributes['aria-pressed'],
  title: bars[0].children.some(child => child.tagName === 'title'),
  activated,
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
        "aria": "High: 12 findings",
        "tabIndex": "0",
        "dimension": "severity",
        "key": "high",
        "selected": "true",
        "title": True,
        "activated": [["severity", "high"]],
        "zeroHasInvalidGeometry": False,
    }
