const API = window.location.origin;
const SAMPLE_PATH =
  "/root/PP/ExaWatcher_gru126171exdcl18.oraclecloud.internal_2026-05-13_19_00_00_3h00m00s";

const state = {
  cases: [],
  selectedId: "",
  modules: [],
  findingCounts: {},
  findings: [],
  snippets: [],
  packet: null,
  activeFindingId: "",
  activeTab: "summary",
  activeModule: "",
  moduleFacets: null,
  selectedMetric: "",
  selectedEntity: "",
  moduleMetrics: [],
};

const els = {
  subtitle: document.querySelector("#case-subtitle"),
  path: document.querySelector("#bundle-path"),
  importButton: document.querySelector("#import-button"),
  refreshButton: document.querySelector("#refresh-button"),
  caseSelect: document.querySelector("#case-select"),
  error: document.querySelector("#error-line"),
  critical: document.querySelector("#critical-count"),
  warning: document.querySelector("#warning-count"),
  metricCount: document.querySelector("#metric-count"),
  moduleCount: document.querySelector("#module-count"),
  tabBar: document.querySelector("#tab-bar"),
  summaryView: document.querySelector("#summary-view"),
  findingsView: document.querySelector("#findings-view"),
  moduleView: document.querySelector("#module-view"),
  moduleSummaryBody: document.querySelector("#module-summary-body"),
  findingList: document.querySelector("#finding-list"),
  findingDetail: document.querySelector("#finding-detail"),
  prompt: document.querySelector("#prompt-packet"),
  copyPrompt: document.querySelector("#copy-prompt"),
  moduleTitle: document.querySelector("#module-title"),
  metricSelect: document.querySelector("#metric-select"),
  entitySelect: document.querySelector("#entity-select"),
  loadModuleMetrics: document.querySelector("#load-module-metrics"),
  moduleChart: document.querySelector("#module-chart"),
  moduleMetricBody: document.querySelector("#module-metric-body"),
};

els.path.value = SAMPLE_PATH;
els.refreshButton.addEventListener("click", refreshCases);
els.importButton.addEventListener("click", importCase);
els.caseSelect.addEventListener("change", () => {
  state.selectedId = els.caseSelect.value;
  if (state.selectedId) {
    loadCase(state.selectedId);
  }
});
els.copyPrompt.addEventListener("click", () => {
  if (state.packet && state.packet.prompt) {
    navigator.clipboard.writeText(state.packet.prompt);
  }
});
els.metricSelect.addEventListener("change", () => {
  state.selectedMetric = els.metricSelect.value;
  state.selectedEntity = "";
  renderModuleControls();
  loadModuleMetrics();
});
els.entitySelect.addEventListener("change", () => {
  state.selectedEntity = els.entitySelect.value;
  loadModuleMetrics();
});
els.loadModuleMetrics.addEventListener("click", loadModuleMetrics);

refreshCases();

async function refreshCases() {
  setError("");
  try {
    const data = await getJson(`${API}/api/cases`);
    state.cases = data;
    if (!state.selectedId && data.length) {
      state.selectedId = data[0].id;
    }
    renderCases();
    if (state.selectedId) {
      await loadCase(state.selectedId);
    }
  } catch (error) {
    setError(error.message || String(error));
  }
}

async function importCase() {
  setBusy(true);
  setError("");
  try {
    const response = await fetch(`${API}/api/cases/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: els.path.value }),
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || "Import failed");
    }
    const data = await response.json();
    state.selectedId = data.case.id;
    state.activeTab = "summary";
    await refreshCases();
  } catch (error) {
    setError(error.message || String(error));
  } finally {
    setBusy(false);
  }
}

async function loadCase(caseId) {
  setBusy(true);
  setError("");
  try {
    const [modulesData, findingsData, packetData] = await Promise.all([
      getJson(`${API}/api/cases/${caseId}/modules`),
      getJson(`${API}/api/cases/${caseId}/findings`),
      getJson(`${API}/api/cases/${caseId}/prompt-packet`),
    ]);
    state.modules = modulesData.modules || [];
    state.findingCounts = modulesData.finding_counts || {};
    state.findings = findingsData.findings || [];
    state.snippets = findingsData.snippets || [];
    state.packet = packetData;
    state.activeFindingId = state.findings[0] ? state.findings[0].id : "";
    if (state.activeModule && !state.modules.some((item) => item.module === state.activeModule)) {
      state.activeModule = "";
      state.activeTab = "summary";
    }
    renderAll();
  } catch (error) {
    setError(error.message || String(error));
  } finally {
    setBusy(false);
  }
}

async function selectModule(module) {
  state.activeTab = `module:${module}`;
  state.activeModule = module;
  state.moduleFacets = null;
  state.selectedMetric = "";
  state.selectedEntity = "";
  state.moduleMetrics = [];
  renderAll();
  await loadModuleFacets(module);
}

async function loadModuleFacets(module) {
  setBusy(true);
  setError("");
  try {
    state.moduleFacets = await getJson(`${API}/api/cases/${state.selectedId}/modules/${encodeURIComponent(module)}/facets`);
    const metrics = state.moduleFacets.metrics || [];
    state.selectedMetric = metrics.length ? metrics[0].metric_name : "";
    renderModuleControls();
    await loadModuleMetrics();
  } catch (error) {
    setError(error.message || String(error));
  } finally {
    setBusy(false);
  }
}

async function loadModuleMetrics() {
  if (!state.selectedId || !state.activeModule || !state.selectedMetric) {
    state.moduleMetrics = [];
    renderModuleChart();
    renderModuleTable();
    return;
  }
  setBusy(true);
  setError("");
  try {
    const params = new URLSearchParams({ metric_name: state.selectedMetric, limit: "20000" });
    if (state.selectedEntity) {
      params.set("entity_name", state.selectedEntity);
    }
    const data = await getJson(
      `${API}/api/cases/${state.selectedId}/modules/${encodeURIComponent(state.activeModule)}/metrics?${params.toString()}`,
    );
    state.moduleMetrics = data.metrics || [];
    renderModuleChart();
    renderModuleTable();
  } catch (error) {
    setError(error.message || String(error));
  } finally {
    setBusy(false);
  }
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${url}`);
  }
  return response.json();
}

function renderAll() {
  renderCases();
  renderOverview();
  renderTabs();
  renderViews();
  renderSummary();
  renderFindings();
  renderDetail();
  renderModuleControls();
  renderModuleChart();
  renderModuleTable();
  els.prompt.value = state.packet && state.packet.prompt ? state.packet.prompt : "";
}

function renderCases() {
  const selectedCase = getSelectedCase();
  els.caseSelect.innerHTML = `<option value="">No case selected</option>${state.cases
    .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`)
    .join("")}`;
  els.caseSelect.value = state.selectedId;
  els.subtitle.textContent = selectedCase
    ? `${selectedCase.host || "Unknown host"} · ${selectedCase.started_at || "Unknown start"} to ${selectedCase.ended_at || "Unknown end"}`
    : "Import a storage cell bundle";
}

function renderOverview() {
  const selectedCase = getSelectedCase();
  const counts = severityCounts();
  els.critical.textContent = String(counts.critical || 0);
  els.warning.textContent = String(counts.warning || 0);
  els.metricCount.textContent = (selectedCase && selectedCase.metric_count ? selectedCase.metric_count : 0).toLocaleString();
  els.moduleCount.textContent = String(state.modules.length || (selectedCase && selectedCase.modules ? selectedCase.modules.length : 0));
}

function renderTabs() {
  const tabs = [
    { id: "summary", label: "Summary" },
    { id: "findings", label: "Findings" },
    ...state.modules.map((item) => ({ id: `module:${item.module}`, label: item.module })),
  ];
  els.tabBar.innerHTML = tabs
    .map((tab) => `<button class="tab-button ${tab.id === state.activeTab ? "active" : ""}" data-id="${escapeHtml(tab.id)}">${escapeHtml(tab.label)}</button>`)
    .join("");
  els.tabBar.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.id;
      if (id.startsWith("module:")) {
        selectModule(id.slice("module:".length));
      } else {
        state.activeTab = id;
        renderAll();
      }
    });
  });
}

function renderViews() {
  els.summaryView.classList.toggle("hidden", state.activeTab !== "summary");
  els.findingsView.classList.toggle("hidden", state.activeTab !== "findings");
  els.moduleView.classList.toggle("hidden", !state.activeTab.startsWith("module:"));
}

function renderSummary() {
  if (!state.modules.length) {
    els.moduleSummaryBody.innerHTML = `<tr><td colspan="6">No modules imported yet.</td></tr>`;
    return;
  }
  els.moduleSummaryBody.innerHTML = state.modules
    .map((module) => {
      const counts = state.findingCounts[module.module] || {};
      const findings = `C:${counts.critical || 0} W:${counts.warning || 0} I:${counts.info || 0}`;
      const command = (module.commands || []).join(" ; ");
      return `
        <tr>
          <td><button class="link-button" data-module="${escapeHtml(module.module)}">${escapeHtml(module.module)}</button></td>
          <td>${Number(module.file_count || 0).toLocaleString()}</td>
          <td>${Number(module.metric_count || 0).toLocaleString()}</td>
          <td>${escapeHtml(formatPeriod(module.started_at, module.ended_at))}</td>
          <td class="command-cell">${escapeHtml(command || module.path || "")}</td>
          <td>${escapeHtml(findings)}</td>
        </tr>
      `;
    })
    .join("");
  els.moduleSummaryBody.querySelectorAll(".link-button").forEach((button) => {
    button.addEventListener("click", () => selectModule(button.dataset.module));
  });
}

function renderFindings() {
  if (!state.findings.length) {
    els.findingList.innerHTML = `<p class="muted panel-empty">No findings loaded.</p>`;
    return;
  }
  els.findingList.innerHTML = state.findings
    .map(
      (finding) => `
        <button class="finding-row ${escapeHtml(finding.severity)} ${finding.id === state.activeFindingId ? "active" : ""}" data-id="${escapeHtml(finding.id)}">
          <span>${escapeHtml(finding.title)}</span>
          <small>${escapeHtml(finding.module)} · ${escapeHtml(finding.entity_name || finding.pattern_id)}</small>
        </button>
      `,
    )
    .join("");
  els.findingList.querySelectorAll(".finding-row").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeFindingId = button.dataset.id;
      renderFindings();
      renderDetail();
    });
  });
}

function renderDetail() {
  const finding = state.findings.find((item) => item.id === state.activeFindingId) || state.findings[0];
  if (!finding) {
    els.findingDetail.innerHTML = `<p class="muted">No findings loaded.</p>`;
    return;
  }
  const snippetMap = new Map(state.snippets.map((snippet) => [snippet.ref, snippet]));
  const snippets = (finding.evidence_refs || []).map((ref) => snippetMap.get(ref)).filter(Boolean);
  els.findingDetail.innerHTML = `
    <div class="severity-pill ${escapeHtml(finding.severity)}">${escapeHtml(finding.severity)}</div>
    <h3>${escapeHtml(finding.title)}</h3>
    <p>${escapeHtml(finding.summary)}</p>
    <dl>
      <dt>Pattern</dt><dd>${escapeHtml(finding.pattern_id)}</dd>
      <dt>Timestamp</dt><dd>${escapeHtml(finding.timestamp || "n/a")}</dd>
      <dt>Metric</dt><dd>${escapeHtml(finding.entity_name)} · ${escapeHtml(finding.metric_name)}</dd>
      <dt>KB</dt><dd>${escapeHtml((finding.kb_ids || []).join(", ") || "No KB match")}</dd>
    </dl>
    <div class="snippet-stack">
      ${snippets.map((snippet) => `<pre>${escapeHtml(snippet.text)}</pre>`).join("")}
    </div>
  `;
}

function renderModuleControls() {
  const module = state.modules.find((item) => item.module === state.activeModule);
  els.moduleTitle.textContent = module ? `${module.module} (${Number(module.file_count || 0).toLocaleString()} files)` : "Module";
  const metrics = state.moduleFacets && state.moduleFacets.metrics ? state.moduleFacets.metrics : [];
  const entities = state.moduleFacets && state.moduleFacets.entities ? state.moduleFacets.entities : [];
  els.metricSelect.innerHTML = metrics.length
    ? metrics.map((item) => `<option value="${escapeHtml(item.metric_name)}">${escapeHtml(item.metric_name)} (${Number(item.count || 0).toLocaleString()})</option>`).join("")
    : `<option value="">No chartable metrics</option>`;
  els.metricSelect.value = state.selectedMetric;
  els.entitySelect.innerHTML = `<option value="">All entities</option>${entities
    .map((item) => `<option value="${escapeHtml(item.entity_name)}">${escapeHtml(item.entity_name)} (${Number(item.count || 0).toLocaleString()})</option>`)
    .join("")}`;
  els.entitySelect.value = state.selectedEntity;
}

function renderModuleChart() {
  if (!state.activeModule) {
    els.moduleChart.innerHTML = `<p class="muted panel-empty">Select a tool tab to chart metrics.</p>`;
    return;
  }
  if (!state.selectedMetric) {
    els.moduleChart.innerHTML = `<p class="muted panel-empty">No numeric metrics were parsed for this tool yet.</p>`;
    return;
  }
  if (!state.moduleMetrics.length) {
    els.moduleChart.innerHTML = `<p class="muted panel-empty">No metric rows match this selection.</p>`;
    return;
  }
  els.moduleChart.innerHTML = buildSvgChart(state.moduleMetrics, state.selectedMetric);
}

function renderModuleTable() {
  const rows = state.moduleMetrics.slice(0, 300);
  els.moduleMetricBody.innerHTML = rows.length
    ? rows
        .map(
          (metric) => `
            <tr>
              <td>${escapeHtml(metric.timestamp)}</td>
              <td>${escapeHtml(metric.entity_name)}</td>
              <td>${escapeHtml(metric.metric_name)}</td>
              <td>${Number(metric.value).toLocaleString()}</td>
              <td>${escapeHtml(metric.unit || "")}</td>
              <td class="command-cell">${escapeHtml(metric.source_file || "")}</td>
            </tr>
          `,
        )
        .join("")
    : `<tr><td colspan="6">No rows to show.</td></tr>`;
}

function buildSvgChart(metrics, metricName) {
  const width = 960;
  const height = 300;
  const pad = 34;
  const sorted = [...metrics].filter((item) => item.timestamp).sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp)));
  const groups = new Map();
  for (const row of sorted) {
    const key = row.entity_name || "value";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const selectedGroups = Array.from(groups.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, state.selectedEntity ? 1 : 8);
  const values = selectedGroups.flatMap((entry) => entry[1].map((row) => Number(row.value))).filter((value) => Number.isFinite(value));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const yMin = min === max ? min - 1 : min;
  const yMax = min === max ? max + 1 : max;
  const timeValues = sorted.map((row) => Date.parse(row.timestamp)).filter((value) => Number.isFinite(value));
  const xMin = Math.min(...timeValues);
  const xMax = Math.max(...timeValues);
  const colors = ["#1f6f5a", "#b7791f", "#4b6f8a", "#8a3a62", "#6b5b95", "#2f7d32", "#9a4d1f", "#555"];
  const x = (timestamp) => {
    const value = Date.parse(timestamp);
    if (!Number.isFinite(value) || xMin === xMax) return pad;
    return pad + ((value - xMin) / (xMax - xMin)) * (width - pad * 2);
  };
  const y = (value) => height - pad - ((value - yMin) / (yMax - yMin)) * (height - pad * 2);
  const lines = selectedGroups
    .map(([entity, rows], index) => {
      const points = rows.map((row) => `${x(row.timestamp).toFixed(1)},${y(Number(row.value)).toFixed(1)}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="${colors[index % colors.length]}" stroke-width="2" />`;
    })
    .join("");
  const legend = selectedGroups
    .map(([entity], index) => `<span><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(entity)}</span>`)
    .join("");
  return `
    <div class="chart-legend">${legend}</div>
    <svg class="line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(metricName)} chart">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#cbd4ce" />
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#cbd4ce" />
      <text x="${pad}" y="18">${escapeHtml(metricName)} max ${max.toFixed(2)}</text>
      <text x="${pad}" y="${height - 8}">min ${min.toFixed(2)}</text>
      ${lines}
    </svg>
  `;
}

function severityCounts() {
  return state.findings.reduce(
    (acc, finding) => {
      acc[finding.severity] = (acc[finding.severity] || 0) + 1;
      return acc;
    },
    { critical: 0, warning: 0, info: 0 },
  );
}

function formatPeriod(startedAt, endedAt) {
  if (!startedAt && !endedAt) return "";
  if (startedAt === endedAt) return startedAt || endedAt;
  return `${startedAt || "?"} to ${endedAt || "?"}`;
}

function getSelectedCase() {
  return state.cases.find((item) => item.id === state.selectedId);
}

function setBusy(value) {
  els.importButton.disabled = value;
  els.refreshButton.disabled = value;
  els.loadModuleMetrics.disabled = value;
}

function setError(message) {
  els.error.textContent = message;
  els.error.classList.toggle("hidden", !message);
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
