(function chartLibrary(global) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const CHART_COLORS = ["#2BC7E3", "#C83A4A", "#2D8B68", "#5B6B77", "#8B5FBF", "#D18B2C"];

  function svgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
  }

  function segmentGroup(item, options, index) {
    const interactive = Boolean(options.dimension && options.onSelect);
    const selected = options.selected?.has(item.key) ?? false;
    const group = svgElement("g", {
      role: interactive ? "button" : "group",
      "aria-label": `${item.label}: ${item.count} ${options.unit || "findings"}`,
      class: selected ? "chart-segment is-selected" : "chart-segment",
    });
    group.style = `--segment-color: ${CHART_COLORS[index % CHART_COLORS.length]}`;
    if (interactive) {
      group.setAttribute("tabindex", "0");
      group.setAttribute("aria-pressed", String(selected));
      group.setAttribute("data-filter-dimension", options.dimension);
      group.setAttribute("data-filter-key", item.key);
      const activate = () => options.onSelect(options.dimension, item.key);
      group.addEventListener("click", activate);
      group.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " " || event.key === "Spacebar") {
          event.preventDefault();
          activate();
        }
      });
    }
    const title = svgElement("title");
    title.textContent = `${item.label}: ${item.count} ${options.unit || "findings"}`;
    group.append(title);
    return group;
  }

  function renderEmpty(container, label) {
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = label;
    container.replaceChildren(empty);
  }

  function renderBarChart(container, series, options = {}) {
    if (!container) return;
    if (!Array.isArray(series) || series.length === 0) {
      renderEmpty(container, "No findings in this signal.");
      return;
    }

    const width = 680;
    const rowHeight = 54;
    const labelWidth = 176;
    const countWidth = 48;
    const plotWidth = width - labelWidth - countWidth - 18;
    const maxCount = Math.max(1, ...series.map(item => Number(item.count) || 0));
    const height = Math.max(92, series.length * rowHeight + 20);
    const svg = svgElement("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "group",
      "aria-label": options.label || "Interactive findings bar chart",
      preserveAspectRatio: "xMinYMin meet",
    });

    series.forEach((item, index) => {
      const count = Math.max(0, Number(item.count) || 0);
      const y = index * rowHeight + 14;
      const group = segmentGroup({ ...item, count }, options, index);
      const label = svgElement("text", { x: "0", y: String(y + 23), class: "chart-label" });
      label.textContent = item.label;
      const track = svgElement("rect", {
        x: String(labelWidth), y: String(y), width: String(plotWidth), height: "30", rx: "2",
        class: "chart-track",
      });
      const bar = svgElement("rect", {
        x: String(labelWidth), y: String(y),
        width: String((count / maxCount) * plotWidth), height: "30", rx: "2",
        class: "chart-bar",
      });
      const numeric = svgElement("text", {
        x: String(width - countWidth + 4), y: String(y + 23), class: "chart-count",
      });
      numeric.textContent = String(count);
      group.append(label, track, bar, numeric);
      svg.append(group);
    });
    container.replaceChildren(svg);
  }

  function renderDonutChart(container, series, options = {}) {
    if (!container) return;
    if (!Array.isArray(series) || series.length === 0) {
      renderEmpty(container, "No coverage records available.");
      return;
    }

    const total = series.reduce((sum, item) => sum + Math.max(0, Number(item.count) || 0), 0);
    const geometryTotal = Math.max(1, total);
    const radius = 62;
    const circumference = 2 * Math.PI * radius;
    const svg = svgElement("svg", {
      viewBox: "0 0 430 180", role: "group",
      "aria-label": options.label || "Entitlement coverage donut chart",
    });
    const track = svgElement("circle", {
      cx: "90", cy: "90", r: String(radius), fill: "none", "stroke-width": "22",
      class: "donut-track",
    });
    svg.append(track);
    let offset = 0;
    series.forEach((item, index) => {
      const count = Math.max(0, Number(item.count) || 0);
      const length = (count / geometryTotal) * circumference;
      const group = segmentGroup(
        { ...item, count },
        { ...options, unit: options.unit || "entitlements" },
        index,
      );
      const segment = svgElement("circle", {
        cx: "90", cy: "90", r: String(radius), fill: "none", "stroke-width": "22",
        "stroke-dasharray": `${length} ${circumference - length}`,
        "stroke-dashoffset": String(-offset),
        transform: "rotate(-90 90 90)", class: "donut-segment",
      });
      const swatch = svgElement("rect", {
        x: "190", y: String(36 + index * 52), width: "12", height: "12", class: "donut-swatch",
      });
      const label = svgElement("text", {
        x: "214", y: String(48 + index * 52), class: "chart-label",
      });
      label.textContent = item.label;
      const numeric = svgElement("text", {
        x: "395", y: String(48 + index * 52), class: "chart-count", "text-anchor": "end",
      });
      numeric.textContent = String(count);
      group.append(segment, swatch, label, numeric);
      svg.append(group);
      offset += length;
    });
    const totalLabel = svgElement("text", {
      x: "90", y: "84", "text-anchor": "middle", class: "donut-total-label",
    });
    totalLabel.textContent = "TOTAL";
    const totalValue = svgElement("text", {
      x: "90", y: "108", "text-anchor": "middle", class: "donut-total-value",
    });
    totalValue.textContent = String(total);
    svg.append(totalLabel, totalValue);
    container.replaceChildren(svg);
  }

  global.renderBarChart = renderBarChart;
  global.renderDonutChart = renderDonutChart;
})(window);
