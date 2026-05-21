import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertTriangle, BarChart3, BookOpen, Clipboard, Database, FileSearch, RefreshCw, Upload } from "lucide-react";
import "./styles.css";

const API = "http://localhost:8000";
const SAMPLE_PATH =
  "/Users/pporacle/Downloads/exacd_logcol_9cce58d4-1ea8-4c4a-8e63-bb44b3fa6044_cmds_gru126171exdcl18_exawatcher_20260513_190000_20260513_220000";

type CaseMeta = {
  id: string;
  name: string;
  source_path: string;
  imported_at: string;
  host: string;
  started_at: string;
  ended_at: string;
  metric_count: number;
  finding_count: number;
  modules: string[];
};

type Finding = {
  id: string;
  pattern_id: string;
  severity: "critical" | "warning" | "info";
  title: string;
  summary: string;
  module: string;
  timestamp: string;
  entity_name: string;
  metric_name: string;
  observed_value: number;
  threshold: number;
  unit: string;
  evidence_refs: string[];
  kb_ids: string[];
};

type Snippet = {
  ref: string;
  source_file: string;
  timestamp: string;
  text: string;
};

type Metric = {
  timestamp: string;
  module: string;
  entity_type: string;
  entity_name: string;
  metric_name: string;
  value: number;
  unit: string;
  source_file: string;
};

type PromptPacket = {
  prompt: string;
  knowledge_base_matches: Record<string, { title: string; explanation: string; recommended_checks: string[] }>;
};

function App() {
  const [cases, setCases] = useState<CaseMeta[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [path, setPath] = useState(SAMPLE_PATH);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [findings, setFindings] = useState<Finding[]>([]);
  const [snippets, setSnippets] = useState<Snippet[]>([]);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [packet, setPacket] = useState<PromptPacket | null>(null);
  const [activeFindingId, setActiveFindingId] = useState("");

  const selectedCase = cases.find((item) => item.id === selectedId);
  const activeFinding = findings.find((item) => item.id === activeFindingId) ?? findings[0];
  const snippetMap = useMemo(() => new Map(snippets.map((snippet) => [snippet.ref, snippet])), [snippets]);
  const severityCounts = useMemo(() => countSeverity(findings), [findings]);
  const chartMetrics = useMemo(() => summarizeMetrics(metrics), [metrics]);

  useEffect(() => {
    void refreshCases();
  }, []);

  useEffect(() => {
    if (selectedId) {
      void loadCase(selectedId);
    }
  }, [selectedId]);

  async function refreshCases() {
    setError("");
    const response = await fetch(`${API}/api/cases`);
    const data = await response.json();
    setCases(data);
    if (!selectedId && data.length) {
      setSelectedId(data[0].id);
    }
  }

  async function importCase() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/cases/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail ?? "Import failed");
      }
      const data = await response.json();
      await refreshCases();
      setSelectedId(data.case.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadCase(caseId: string) {
    setBusy(true);
    setError("");
    try {
      const [findingsResponse, timelineResponse, packetResponse] = await Promise.all([
        fetch(`${API}/api/cases/${caseId}/findings`),
        fetch(`${API}/api/cases/${caseId}/timeline?limit=1200`),
        fetch(`${API}/api/cases/${caseId}/prompt-packet`),
      ]);
      if (!findingsResponse.ok || !timelineResponse.ok || !packetResponse.ok) {
        throw new Error("Unable to load selected case");
      }
      const findingsData = await findingsResponse.json();
      const timelineData = await timelineResponse.json();
      const packetData = await packetResponse.json();
      setFindings(findingsData.findings);
      setSnippets(findingsData.snippets);
      setMetrics(timelineData.metrics);
      setPacket(packetData);
      setActiveFindingId(findingsData.findings[0]?.id ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <h1>ExaWatcher Workbench</h1>
          <p>{selectedCase ? `${selectedCase.host || "Unknown host"} · ${selectedCase.started_at || "Unknown start"} to ${selectedCase.ended_at || "Unknown end"}` : "Import a storage cell bundle"}</p>
        </div>
        <button className="icon-button" onClick={refreshCases} title="Refresh cases">
          <RefreshCw size={18} />
        </button>
      </section>

      <section className="control-band">
        <label className="path-input">
          <span>Bundle path</span>
          <input value={path} onChange={(event) => setPath(event.target.value)} />
        </label>
        <button className="primary" onClick={importCase} disabled={busy}>
          <Upload size={18} />
          Import
        </button>
        <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
          <option value="">No case selected</option>
          {cases.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </section>

      {error && <div className="error-line">{error}</div>}

      <section className="overview-grid">
        <MetricTile icon={<AlertTriangle size={18} />} label="Critical" value={severityCounts.critical} tone="critical" />
        <MetricTile icon={<FileSearch size={18} />} label="Warnings" value={severityCounts.warning} tone="warning" />
        <MetricTile icon={<Database size={18} />} label="Metrics" value={selectedCase?.metric_count ?? 0} />
        <MetricTile icon={<BookOpen size={18} />} label="Modules" value={selectedCase?.modules.length ?? 0} />
      </section>

      <section className="work-grid">
        <div className="panel findings-panel">
          <div className="panel-title">
            <AlertTriangle size={18} />
            <h2>Findings</h2>
          </div>
          <div className="finding-list">
            {findings.map((finding) => (
              <button
                key={finding.id}
                className={`finding-row ${finding.severity} ${activeFinding?.id === finding.id ? "active" : ""}`}
                onClick={() => setActiveFindingId(finding.id)}
              >
                <span>{finding.title}</span>
                <small>{finding.module} · {finding.entity_name || finding.pattern_id}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="panel detail-panel">
          <div className="panel-title">
            <FileSearch size={18} />
            <h2>Evidence</h2>
          </div>
          {activeFinding ? (
            <FindingDetail finding={activeFinding} snippets={activeFinding.evidence_refs.map((ref) => snippetMap.get(ref)).filter(Boolean) as Snippet[]} />
          ) : (
            <p className="muted">No findings loaded.</p>
          )}
        </div>

        <div className="panel chart-panel">
          <div className="panel-title">
            <BarChart3 size={18} />
            <h2>Metric Timeline</h2>
          </div>
          <MetricBars metrics={chartMetrics} />
        </div>

        <div className="panel prompt-panel">
          <div className="panel-title">
            <Clipboard size={18} />
            <h2>Prompt Packet</h2>
            <button className="icon-button" title="Copy prompt packet" onClick={() => packet?.prompt && navigator.clipboard.writeText(packet.prompt)}>
              <Clipboard size={16} />
            </button>
          </div>
          <textarea value={packet?.prompt ?? ""} readOnly />
        </div>
      </section>
    </main>
  );
}

function MetricTile({ icon, label, value, tone = "" }: { icon: React.ReactNode; label: string; value: number; tone?: string }) {
  return (
    <div className={`metric-tile ${tone}`}>
      {icon}
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}

function FindingDetail({ finding, snippets }: { finding: Finding; snippets: Snippet[] }) {
  return (
    <div className="finding-detail">
      <div className={`severity-pill ${finding.severity}`}>{finding.severity}</div>
      <h3>{finding.title}</h3>
      <p>{finding.summary}</p>
      <dl>
        <dt>Pattern</dt>
        <dd>{finding.pattern_id}</dd>
        <dt>Timestamp</dt>
        <dd>{finding.timestamp || "n/a"}</dd>
        <dt>Metric</dt>
        <dd>{finding.entity_name} · {finding.metric_name}</dd>
        <dt>KB</dt>
        <dd>{finding.kb_ids.join(", ") || "No KB match"}</dd>
      </dl>
      <div className="snippet-stack">
        {snippets.map((snippet) => (
          <pre key={snippet.ref}>{snippet.text}</pre>
        ))}
      </div>
    </div>
  );
}

function MetricBars({ metrics }: { metrics: { label: string; value: number }[] }) {
  const max = Math.max(1, ...metrics.map((item) => item.value));
  return (
    <div className="metric-bars">
      {metrics.map((item) => (
        <div className="bar-row" key={item.label}>
          <span>{item.label}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${Math.max(3, (item.value / max) * 100)}%` }} />
          </div>
          <strong>{item.value.toFixed(item.value > 10 ? 0 : 1)}</strong>
        </div>
      ))}
    </div>
  );
}

function countSeverity(findings: Finding[]) {
  return findings.reduce(
    (counts, finding) => {
      counts[finding.severity] += 1;
      return counts;
    },
    { critical: 0, warning: 0, info: 0 },
  );
}

function summarizeMetrics(metrics: Metric[]) {
  const interesting = metrics.filter((metric) =>
    ["%util", "r_await", "w_await", "%idle", "%iowait", "%soft", "si", "so"].includes(metric.metric_name),
  );
  const grouped = new Map<string, number[]>();
  for (const metric of interesting) {
    const label = `${metric.module} ${metric.metric_name}`;
    grouped.set(label, [...(grouped.get(label) ?? []), metric.metric_name === "%idle" ? 100 - metric.value : metric.value]);
  }
  return Array.from(grouped.entries())
    .map(([label, values]) => ({ label, value: values.reduce((sum, value) => sum + value, 0) / values.length }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 12);
}

createRoot(document.getElementById("root")!).render(<App />);

