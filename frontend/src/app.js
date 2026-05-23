const API = window.location.origin;
const SAMPLE_PATH =
  "/root/PP/ExaWatcher_gru126171exdcl18.oraclecloud.internal_2026-05-13_19_00_00_3h00m00s";

const state = {
  cases: [],
  selectedId: "",
  findings: [],
  snippets: [],
  metrics: [],
  packet: null,
  activeFindingId: "",
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
  findingList: document.querySelector("#finding-list"),
  findingDetail: document.querySelector("#finding-detail"),
  metricBars: document.querySelector("#metric-bars"),
  prompt: document.querySelector("#prompt-packet"),
  copyPrompt: document.querySelector("#copy-prompt"),
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
  if (state.packet?.prompt) {
    navigator.clipboard.writeText(state.packet.prompt);
  }
});

refreshCases();

async function refreshCases() {
  setError("");
  const data = await getJson(`${API}/api/cases`);
  state.cases = data;
  if (!state.selectedId && data.length) {
    state.selectedId = data[0].id;
  }
  renderCases();
  if (state.selectedId) {
    await loadCase(state.selectedId);
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
    const [findingsData, timelineData, packetData] = await Promise.all([
      getJson(`${API}/api/cases/${caseId}/findings`),
      getJson(`${API}/api/cases/${caseId}/timeline?limit=1200`),
      getJson(`${API}/api/cases/${caseId}/prompt-packet`),
    ]);
    state.findings = findingsData.findings || [];
    state.snippets = findingsData.snippets || [];
    state.metrics = timelineData.metrics || [];
    state.packet = packetData;
    state.activeFindingId = state.findings[0]?.id || "";
    renderAll();
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
  renderFindings();
  renderDetail();
  renderMetrics();
  els.prompt.value = state.packet?.prompt || "";
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
  const counts = state.findings.reduce(
    (acc, finding) => {
      acc[finding.severity] = (acc[finding.severity] || 0) + 1;
      return acc;
    },
    { critical: 0, warning: 0, info: 0 },
  );
  els.critical.textContent = String(counts.critical || 0);
  els.warning.textContent = String(counts.warning || 0);
  els.metricCount.textContent = (selectedCase?.metric_count || 0).toLocaleString();
  els.moduleCount.textContent = String(selectedCase?.modules?.length || 0);
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

function renderMetrics() {
  const summarized = summarizeMetrics(state.metrics);
  const max = Math.max(1, ...summarized.map((item) => item.value));
  els.metricBars.innerHTML = summarized
    .map((item) => {
      const width = Math.max(3, (item.value / max) * 100);
      return `
        <div class="bar-row">
          <span>${escapeHtml(item.label)}</span>
          <div class="bar-track"><div class="bar-fill" style="width: ${width}%"></div></div>
          <strong>${item.value.toFixed(item.value > 10 ? 0 : 1)}</strong>
        </div>
      `;
    })
    .join("");
}

function summarizeMetrics(metrics) {
  const wanted = new Set(["%util", "r_await", "w_await", "%idle", "%iowait", "%soft", "si", "so"]);
  const grouped = new Map();
  for (const metric of metrics) {
    if (!wanted.has(metric.metric_name)) continue;
    const label = `${metric.module} ${metric.metric_name}`;
    const value = metric.metric_name === "%idle" ? 100 - metric.value : metric.value;
    grouped.set(label, [...(grouped.get(label) || []), value]);
  }
  return Array.from(grouped.entries())
    .map(([label, values]) => ({ label, value: values.reduce((sum, value) => sum + value, 0) / values.length }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);
}

function getSelectedCase() {
  return state.cases.find((item) => item.id === state.selectedId);
}

function setBusy(value) {
  els.importButton.disabled = value;
  els.refreshButton.disabled = value;
}

function setError(message) {
  els.error.textContent = message;
  els.error.classList.toggle("hidden", !message);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
