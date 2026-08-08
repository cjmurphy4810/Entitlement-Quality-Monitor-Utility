(function dashboardApplication(global) {
  "use strict";

  const FILTER_KEYS = ["state", "severity", "targetType", "rule"];
  const STATUS_BUCKETS = {
    not_started: new Set(["not_started", "open"]),
    in_progress: new Set(["in_progress", "pending_approval", "approved", "manual_repair"]),
    complete: new Set(["complete", "resolved", "rejected"]),
  };

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function titleCase(value) {
    return String(value).replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
  }

  class DashboardController {
    constructor(root, initialData, options = {}) {
      this.root = root;
      this.data = initialData;
      this.fetchImpl = options.fetchImpl || global.fetch.bind(global);
      this.history = options.history || global.history;
      this.location = options.location || global.location;
      this.filters = new Map();
      FILTER_KEYS.forEach(dimension => {
        this.filters.set(dimension, new Set(initialData.filters?.[dimension] || []));
      });
      this.search = initialData.filters?.search || "";
      this.page = initialData.filters?.page || 1;
      this.pageSize = initialData.filters?.pageSize || 50;
      this.abortController = null;
      this.bindControls();
      global.addEventListener?.("popstate", () => this.restoreFromLocation());
      this.render(initialData);
    }

    bindControls() {
      document.querySelector("#clear-filters")?.addEventListener("click", () => this.clearFilters());
      document.querySelector("#retry-dashboard")?.addEventListener("click", () => this.refresh());
      document.querySelector("#previous-page")?.addEventListener("click", () => this.setPage(this.page - 1));
      document.querySelector("#next-page")?.addEventListener("click", () => this.setPage(this.page + 1));
      document.querySelector("#dashboard-search")?.addEventListener("submit", event => {
        event.preventDefault();
        this.search = document.querySelector("#finding-search")?.value.trim() || "";
        this.page = 1;
        this.refresh();
      });
    }

    toggleFilter(dimension, key) {
      const selected = this.filters.get(dimension) ?? new Set();
      selected.has(key) ? selected.delete(key) : selected.add(key);
      this.filters.set(dimension, selected);
      this.page = 1;
      return this.refresh();
    }

    clearFilters() {
      FILTER_KEYS.forEach(dimension => this.filters.set(dimension, new Set()));
      this.search = "";
      this.page = 1;
      const searchInput = document.querySelector("#finding-search");
      if (searchInput) searchInput.value = "";
      return this.refresh();
    }

    setPage(page) {
      const totalPages = this.data.pagination?.totalPages || 0;
      if (page < 1 || (totalPages && page > totalPages)) return Promise.resolve();
      this.page = page;
      return this.refresh();
    }

    queryString() {
      const params = new URLSearchParams();
      FILTER_KEYS.forEach(dimension => {
        this.filters.get(dimension)?.forEach(value => params.append(dimension, value));
      });
      if (this.search) params.set("search", this.search);
      params.set("page", String(this.page));
      params.set("pageSize", String(this.pageSize));
      return params.toString();
    }

    restoreFromLocation() {
      const params = new URLSearchParams(this.location.search);
      FILTER_KEYS.forEach(dimension => {
        this.filters.set(dimension, new Set(params.getAll(dimension)));
      });
      this.search = params.get("search")?.trim() || "";
      const parsedPage = Number.parseInt(params.get("page") || "1", 10);
      const parsedPageSize = Number.parseInt(params.get("pageSize") || "50", 10);
      this.page = parsedPage > 0 ? parsedPage : 1;
      this.pageSize = parsedPageSize > 0 ? parsedPageSize : 50;
      const searchInput = document.querySelector("#finding-search");
      if (searchInput) searchInput.value = this.search;
      return this.refresh({ updateHistory: false });
    }

    async refresh({ updateHistory = true } = {}) {
      this.abortController?.abort();
      const requestController = new AbortController();
      this.abortController = requestController;
      const query = this.queryString();
      const endpoint = `/ctadmin/api/dashboard?${query}`;
      this.root.setAttribute("aria-busy", "true");
      try {
        const response = await this.fetchImpl(endpoint, {
          headers: { Accept: "application/json" },
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error(`Dashboard request failed with ${response.status}`);
        const payload = await response.json();
        this.data = payload;
        this.page = payload.pagination.page;
        this.render(payload);
        if (updateHistory) this.history?.pushState?.({}, "", `/ctadmin/dashboard?${query}`);
        this.setError(false);
        return payload;
      } catch (error) {
        if (error.name !== "AbortError") this.setError(true);
        return null;
      } finally {
        if (this.abortController === requestController) {
          this.abortController = null;
          this.root.setAttribute("aria-busy", "false");
        }
      }
    }

    setError(visible) {
      const error = document.querySelector("#dashboard-error");
      if (error) error.hidden = !visible;
    }

    selectedStatusBuckets() {
      const selectedStates = this.filters.get("state") || new Set();
      return new Set(Object.entries(STATUS_BUCKETS)
        .filter(([, members]) => [...selectedStates].some(value => members.has(value)))
        .map(([bucket]) => bucket));
    }

    render(payload) {
      const kpis = {
        "#kpi-total": payload.kpis.totalFindings,
        "#kpi-critical": payload.kpis.criticalFindings,
        "#kpi-high": payload.kpis.highFindings,
        "#kpi-not-started": payload.kpis.notStartedFindings,
        "#kpi-in-progress": payload.kpis.inProgressFindings,
      };
      Object.entries(kpis).forEach(([selector, value]) => {
        const target = document.querySelector(selector);
        if (target) target.textContent = String(value);
      });

      const onSelect = (dimension, key) => this.toggleFilter(dimension, key);
      global.renderBarChart(document.querySelector("#chart-status"), payload.series.status, {
        dimension: "state", selected: this.selectedStatusBuckets(), onSelect,
        label: "Findings by workflow status",
      });
      global.renderBarChart(document.querySelector("#chart-severity"), payload.series.severity, {
        dimension: "severity", selected: this.filters.get("severity"), onSelect,
        label: "Findings by severity",
      });
      global.renderBarChart(document.querySelector("#chart-target-type"), payload.series.targetType, {
        dimension: "targetType", selected: this.filters.get("targetType"), onSelect,
        label: "Findings by target type",
      });
      global.renderBarChart(document.querySelector("#chart-rule"), payload.series.rule, {
        dimension: "rule", selected: this.filters.get("rule"), onSelect,
        label: "Findings by control rule",
      });
      global.renderDonutChart(document.querySelector("#chart-coverage"), [
        { key: "withFindings", label: "With findings", count: payload.coverage.withFindings },
        { key: "withoutFindings", label: "Without findings", count: payload.coverage.withoutFindings },
      ], { label: "Entitlement coverage" });
      this.renderFilterSummary(payload);
      this.renderRows(payload.rows, payload.pagination);
    }

    renderFilterSummary(payload) {
      const summary = document.querySelector("#filter-summary");
      const clear = document.querySelector("#clear-filters");
      if (!summary || !clear) return;
      const active = [];
      FILTER_KEYS.forEach(dimension => {
        this.filters.get(dimension)?.forEach(key => active.push({ dimension, key }));
      });
      summary.replaceChildren();
      if (active.length === 0 && !this.search) {
        summary.append(createElement("span", "", "Evaluation scope: all active records"));
      } else {
        summary.append(createElement("span", "scope-label", "Active signal"));
        active.forEach(({ dimension, key }) => {
          const token = createElement("button", "filter-token", `${titleCase(dimension)}: ${titleCase(key)} ×`);
          token.type = "button";
          token.setAttribute("aria-label", `Remove ${titleCase(dimension)} filter ${titleCase(key)}`);
          token.addEventListener("click", () => this.toggleFilter(dimension, key));
          summary.append(token);
        });
        if (this.search) {
          const searchToken = createElement("button", "filter-token", `Search: ${this.search} ×`);
          searchToken.type = "button";
          searchToken.setAttribute("aria-label", `Clear search ${this.search}`);
          searchToken.addEventListener("click", () => {
            this.search = "";
            const input = document.querySelector("#finding-search");
            if (input) input.value = "";
            this.page = 1;
            this.refresh();
          });
          summary.append(searchToken);
        }
      }
      clear.disabled = active.length === 0 && !this.search;
      const count = document.querySelector("#results-count");
      if (count) count.textContent = `${payload.pagination.total} matching findings`;
    }

    renderRows(rows, pagination) {
      const body = document.querySelector("#findings-results");
      if (!body) return;
      body.replaceChildren();
      if (rows.length === 0) {
        const row = createElement("tr", "empty-row");
        const cell = createElement("td", "", "No findings match this signal. Clear a filter or broaden the search.");
        cell.colSpan = 7;
        row.append(cell);
        body.append(row);
      } else {
        rows.forEach(finding => {
          const row = createElement("tr");
          const findingCell = createElement("td");
          const link = createElement("a", "finding-link", finding.violationId);
          link.href = `/ctadmin/findings/${encodeURIComponent(finding.violationId)}`;
          findingCell.append(link);
          row.append(
            findingCell,
            createElement("td", "", finding.userName),
            createElement("td", "mono-cell", finding.ruleId),
            createElement("td", `severity severity-${finding.severity.toLowerCase()}`, finding.severity),
            createElement("td", "", finding.status),
            createElement("td", "mono-cell", `${finding.targetType} / ${finding.targetId}`),
            createElement("td", "mono-cell", new Date(finding.detectedAt).toLocaleDateString()),
          );
          body.append(row);
        });
      }
      const status = document.querySelector("#page-status");
      if (status) status.textContent = pagination.totalPages
        ? `Page ${pagination.page} of ${pagination.totalPages}` : "No result pages";
      const previous = document.querySelector("#previous-page");
      const next = document.querySelector("#next-page");
      if (previous) previous.disabled = pagination.page <= 1;
      if (next) next.disabled = pagination.totalPages === 0 || pagination.page >= pagination.totalPages;
    }
  }

  global.DashboardController = DashboardController;
  document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("#dashboard");
    const dataScript = document.querySelector("#dashboard-data");
    if (!root || !dataScript) return;
    try {
      const controller = new DashboardController(root, JSON.parse(dataScript.textContent));
      global.ctadminDashboard = controller;
    } catch (_error) {
      const error = document.querySelector("#dashboard-error");
      if (error) error.hidden = false;
    }
  });
})(window);
