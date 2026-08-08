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

  class RepairDrawer {
    constructor(root = document, options = {}) {
      this.root = root;
      this.drawer = root.querySelector("#repair-drawer");
      this.backdrop = root.querySelector("#repair-drawer-backdrop");
      this.closeButton = root.querySelector("#repair-drawer-close");
      this.cancelButton = root.querySelector("#repair-cancel");
      this.form = root.querySelector("#repair-form");
      this.fields = root.querySelector("#repair-fields");
      this.loading = root.querySelector("#repair-drawer-loading");
      this.error = root.querySelector("#repair-drawer-error");
      this.content = root.querySelector("#repair-drawer-content");
      this.outcome = root.querySelector("#repair-outcome");
      this.previewId = root.querySelector("#repair-preview-id");
      this.previewReason = root.querySelector("#repair-preview-reason");
      this.previewEvidence = root.querySelector("#repair-preview-evidence");
      this.confirmButton = root.querySelector("#repair-confirm");
      this.fetchImpl = options.fetchImpl || global.fetch.bind(global);
      this.onSuccess = options.onSuccess || (payload => {
        if (global.ctadminDashboard?.refresh) {
          global.ctadminDashboard.refresh();
        } else {
          global.setTimeout?.(() => global.location?.reload?.(), 900);
        }
        return payload;
      });
      this.findingId = null;
      this.preview = null;
      this.returnFocus = null;
      this.previewController = null;
      this.previewGeneration = 0;
      if (!this.drawer) return;
      this.closeButton?.addEventListener("click", () => this.close());
      this.cancelButton?.addEventListener("click", () => this.close());
      this.backdrop?.addEventListener("click", () => this.close());
      this.form?.addEventListener("submit", event => this.submit(event));
      this.drawer.addEventListener("keydown", event => this.handleKeydown(event));
    }

    focusableElements() {
      return [...this.drawer.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])'
      )].filter(element => !element.hidden && !element.closest?.("[hidden]"));
    }

    handleKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = this.focusableElements();
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    async open(findingId, trigger = document.activeElement) {
      if (!this.drawer) return null;
      this.previewController?.abort();
      const requestController = new AbortController();
      this.previewController = requestController;
      const generation = ++this.previewGeneration;
      this.findingId = findingId;
      this.returnFocus = trigger;
      this.preview = null;
      this.drawer.hidden = false;
      this.drawer.setAttribute("aria-hidden", "false");
      if (this.backdrop) this.backdrop.hidden = false;
      if (this.loading) this.loading.hidden = false;
      if (this.content) this.content.hidden = true;
      this.setError("");
      this.setOutcome("");
      this.closeButton?.focus();
      try {
        const response = await this.fetchImpl(
          `/ctadmin/api/findings/${encodeURIComponent(findingId)}/repair-preview`,
          { headers: { Accept: "application/json" }, signal: requestController.signal },
        );
        const payload = await response.json();
        if (generation !== this.previewGeneration || this.findingId !== findingId) return null;
        if (!response.ok) throw new Error(payload.detail || "Repair preview could not be loaded.");
        this.preview = payload;
        this.renderPreview(payload);
        if (this.loading) this.loading.hidden = true;
        if (this.content) this.content.hidden = false;
        this.focusableElements()[0]?.focus();
        return payload;
      } catch (error) {
        if (generation !== this.previewGeneration || error.name === "AbortError") return null;
        if (this.loading) this.loading.hidden = true;
        this.setError(error.message || "Repair preview could not be loaded.");
        return null;
      } finally {
        if (this.previewController === requestController) this.previewController = null;
      }
    }

    close() {
      if (!this.drawer) return;
      this.previewController?.abort();
      this.previewController = null;
      this.previewGeneration += 1;
      this.preview = null;
      this.findingId = null;
      this.drawer.hidden = true;
      this.drawer.setAttribute("aria-hidden", "true");
      if (this.backdrop) this.backdrop.hidden = true;
      this.returnFocus?.focus?.();
    }

    setError(message) {
      if (!this.error) return;
      this.error.textContent = message;
      this.error.hidden = !message;
    }

    setOutcome(message, success = false) {
      if (!this.outcome) return;
      this.outcome.textContent = message;
      this.outcome.classList.toggle("is-success", Boolean(message && success));
      this.outcome.hidden = !message;
    }

    renderPreview(payload) {
      if (this.previewId) this.previewId.textContent = `${payload.violationId} / ${payload.ruleId}`;
      if (this.previewReason) this.previewReason.textContent = payload.reason;
      if (this.previewEvidence) this.previewEvidence.textContent = JSON.stringify(payload.evidence, null, 2);
      if (this.confirmButton) this.confirmButton.textContent = payload.confirmLabel || "Confirm repair";
      this.fields?.replaceChildren();
      (payload.fields || []).forEach(field => this.renderField(field));
    }

    renderField(field) {
      if (!this.fields) return;
      if (field.type === "radio") {
        const group = createElement("fieldset", "repair-choice-group");
        group.append(createElement("legend", "", field.label));
        (field.options || []).forEach(option => {
          const label = createElement("label", "repair-choice");
          const input = createElement("input");
          input.type = "radio"; input.name = field.name; input.value = option.value;
          input.required = Boolean(field.required);
          label.append(input, createElement("span", "", option.label));
          group.append(label);
        });
        this.fields.append(group);
        return;
      }
      if (field.type === "readonly") {
        const panel = createElement("div", "repair-readonly");
        panel.append(createElement("strong", "", field.label), createElement("p", "", field.value));
        this.fields.append(panel);
        return;
      }
      const label = createElement("label", "repair-field");
      label.append(createElement("span", "", field.label));
      let input;
      if (field.type === "textarea") {
        input = createElement("textarea");
        input.rows = 6;
        input.value = field.value || "";
      } else if (field.type === "select" || field.type === "multiselect") {
        input = createElement("select");
        input.multiple = field.type === "multiselect";
        if (!input.multiple) {
          const placeholder = createElement("option", "", "Select a resource");
          placeholder.value = "";
          placeholder.selected = true;
          placeholder.disabled = true;
          input.append(placeholder);
        }
        (field.options || []).forEach(option => {
          const element = createElement("option", "", option.label);
          element.value = option.value;
          input.append(element);
        });
      } else if (field.type === "checkbox") {
        input = createElement("input");
        input.type = "checkbox";
        label.className = "repair-choice acknowledgement";
      } else {
        input = createElement("input");
        input.type = field.type || "text";
        input.value = field.value || "";
      }
      input.name = field.name;
      input.required = Boolean(field.required);
      label.append(input);
      this.fields.append(label);
    }

    submission() {
      const values = { ...(this.preview?.submission || {}) };
      const named = this.fields ? [...this.fields.querySelectorAll("[name]")] : [];
      named.forEach(input => {
        if (input.type === "radio") {
          if (input.checked) values[input.name] = input.value;
        } else if (input.type === "checkbox") {
          values[input.name] = Boolean(input.checked);
        } else if (input.multiple) {
          values[input.name] = [...input.selectedOptions].map(option => option.value);
        } else {
          values[input.name] = input.value;
        }
      });
      return values;
    }

    async submit(event) {
      event.preventDefault();
      if (!this.preview || !this.findingId) return null;
      this.setError("");
      this.setOutcome("Applying repair and re-running all controls…");
      if (this.confirmButton) this.confirmButton.disabled = true;
      try {
        const response = await this.fetchImpl(
          `/ctadmin/actions/findings/${encodeURIComponent(this.findingId)}/repair`,
          {
            method: "POST",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
              "X-CSRF-Token": this.drawer.dataset.csrfToken,
            },
            body: JSON.stringify(this.submission()),
          },
        );
        const payload = await response.json();
        if (!response.ok) {
          this.setOutcome("");
          this.setError(payload.detail || "Repair could not be completed.");
          return null;
        }
        this.setOutcome(`Repair verified. ${payload.summary}`, true);
        this.outcome?.focus?.();
        await this.onSuccess(payload);
        return payload;
      } catch (_error) {
        this.setOutcome("");
        this.setError("Repair could not be completed. Check the connection and try again.");
        return null;
      } finally {
        if (this.confirmButton) this.confirmButton.disabled = false;
      }
    }
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
  global.RepairDrawer = RepairDrawer;
  document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("#dashboard");
    const dataScript = document.querySelector("#dashboard-data");
    if (root && dataScript) {
      try {
        const controller = new DashboardController(root, JSON.parse(dataScript.textContent));
        global.ctadminDashboard = controller;
      } catch (_error) {
        const error = document.querySelector("#dashboard-error");
        if (error) error.hidden = false;
      }
    }
    const drawerRoot = document.querySelector("#repair-drawer");
    if (!drawerRoot) return;
    const drawer = new RepairDrawer(document);
    global.ctadminRepairDrawer = drawer;
    document.querySelectorAll(".repair-trigger").forEach(trigger => {
      trigger.addEventListener("click", () => drawer.open(trigger.dataset.findingId, trigger));
    });
  });
})(window);
