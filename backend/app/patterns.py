from __future__ import annotations

import statistics
from collections import defaultdict

from .kb import KnowledgeEntry, match_kb
from .models import Finding, MetricRow
from .parser import EXPECTED_MODULES


THRESHOLDS = {
    "io.high_util": 85.0,
    "io.high_read_await": 20.0,
    "io.high_write_await": 50.0,
    "cpu.high_usage": 90.0,
    "cpu.iowait": 20.0,
    "cpu.softirq": 25.0,
    "memory.low_available": 5.0,
    "memory.swap_activity": 0.0,
    "network.error_signal": 0.0,
    "roce.error_signal": 0.0,
    "cell.error_signal": 0.0,
    "cell.latency_signal": 0.0,
    "cell.disk_state": 0.0,
}


def detect_findings(case_id: str, metrics: list[MetricRow], modules_seen: set[str], kb_entries: list[KnowledgeEntry]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(metric_threshold_findings(case_id, metrics, kb_entries))
    findings.extend(device_skew_findings(case_id, metrics, kb_entries))
    findings.extend(coverage_findings(case_id, modules_seen, kb_entries))
    return findings


def metric_threshold_findings(case_id: str, metrics: list[MetricRow], kb_entries: list[KnowledgeEntry]) -> list[Finding]:
    best_by_key: dict[tuple[str, str, str, str], tuple[MetricRow, str, float, float]] = {}
    for metric in metrics:
        pattern_id, threshold, observed = classify_metric(metric)
        if not pattern_id:
            continue
        if observed <= threshold:
            continue
        key = (pattern_id, metric.module, metric.entity_name, metric.metric_name)
        previous = best_by_key.get(key)
        if previous is None or observed > previous[2]:
            best_by_key[key] = (metric, pattern_id, observed, threshold)

    findings: list[Finding] = []
    sorted_candidates = sorted(best_by_key.values(), key=lambda item: item[2] - item[3], reverse=True)[:250]
    for metric, pattern_id, observed, threshold in sorted_candidates:
        findings.append(
            Finding(
                id=f"f{len(findings) + 1}",
                case_id=case_id,
                pattern_id=pattern_id,
                severity=severity_for(pattern_id, observed, threshold),
                title=title_for(pattern_id),
                summary=f"{metric.module} {metric.entity_name} {metric.metric_name} reached {observed:g}{format_unit(metric.unit)}.",
                module=metric.module,
                timestamp=metric.timestamp,
                entity_type=metric.entity_type,
                entity_name=metric.entity_name,
                metric_name=metric.metric_name,
                observed_value=observed,
                threshold=threshold,
                unit=metric.unit,
                evidence_refs=[metric.raw_snippet_ref] if metric.raw_snippet_ref else [],
                kb_ids=match_kb(pattern_id, kb_entries),
            )
        )
    return findings


def classify_metric(metric: MetricRow) -> tuple[str, float, float]:
    name = metric.metric_name.lower()
    module = metric.module.lower()
    value = metric.value
    if metric.module == "Iostat" and metric.metric_name == "%util":
        return "io.high_util", THRESHOLDS["io.high_util"], value
    if metric.module == "Iostat" and metric.metric_name == "r_await":
        return "io.high_read_await", THRESHOLDS["io.high_read_await"], value
    if metric.module == "Iostat" and metric.metric_name == "w_await":
        return "io.high_write_await", THRESHOLDS["io.high_write_await"], value
    if metric.module == "Mpstat" and metric.entity_name == "all" and metric.metric_name == "%idle":
        return "cpu.high_usage", THRESHOLDS["cpu.high_usage"], 100 - value
    if metric.module == "Mpstat" and metric.entity_name == "all" and metric.metric_name == "%iowait":
        return "cpu.iowait", THRESHOLDS["cpu.iowait"], value
    if metric.module == "Mpstat" and metric.entity_name == "all" and metric.metric_name == "%soft":
        return "cpu.softirq", THRESHOLDS["cpu.softirq"], value
    if metric.module == "Vmstat" and metric.metric_name in {"si", "so"}:
        return "memory.swap_activity", THRESHOLDS["memory.swap_activity"], value
    if metric.module == "Meminfo" and name in {"memavailable", "memfree"}:
        total = 0.0
        # evaluated in low-memory helper below instead
        return "", total, value
    if metric.entity_type == "signal":
        if "roce" in module or "ib" in module:
            return "roce.error_signal", THRESHOLDS["roce.error_signal"], value
        if "net" in module or "rds" in module:
            return "network.error_signal", THRESHOLDS["network.error_signal"], value
        if "cell" in module or "ecstat" in module or "disk" in module:
            lower = name + " " + metric.entity_name.lower()
            if "latency" in lower:
                return "cell.latency_signal", THRESHOLDS["cell.latency_signal"], value
            if "offline" in lower:
                return "cell.disk_state", THRESHOLDS["cell.disk_state"], value
            return "cell.error_signal", THRESHOLDS["cell.error_signal"], value
    return "", 0.0, value


def device_skew_findings(case_id: str, metrics: list[MetricRow], kb_entries: list[KnowledgeEntry]) -> list[Finding]:
    candidates: list[Finding] = []
    by_ts: dict[str, list[MetricRow]] = defaultdict(list)
    for metric in metrics:
        if metric.module == "Iostat" and metric.metric_name == "%util" and metric.entity_name.startswith(("sd", "nvme", "md")):
            by_ts[metric.timestamp].append(metric)
    for timestamp, rows in by_ts.items():
        if len(rows) < 4:
            continue
        values = [row.value for row in rows]
        median = statistics.median(values)
        if median <= 0:
            continue
        for row in rows:
            if row.value >= 70 and row.value >= median * 3:
                candidates.append(
                    Finding(
                        id=f"skew{len(candidates) + 1}",
                        case_id=case_id,
                        pattern_id="io.device_skew",
                        severity="warning",
                        title="Device utilization skew",
                        summary=f"{row.entity_name} was {row.value:g}% utilized while peer median was {median:g}%.",
                        module=row.module,
                        timestamp=timestamp,
                        entity_type=row.entity_type,
                        entity_name=row.entity_name,
                        metric_name=row.metric_name,
                        observed_value=row.value,
                        threshold=median * 3,
                        unit=row.unit,
                        evidence_refs=[row.raw_snippet_ref] if row.raw_snippet_ref else [],
                        kb_ids=match_kb("io.device_skew", kb_entries),
                    )
                )
    candidates.sort(key=lambda item: item.observed_value - item.threshold, reverse=True)
    return candidates[:100]


def coverage_findings(case_id: str, modules_seen: set[str], kb_entries: list[KnowledgeEntry]) -> list[Finding]:
    findings: list[Finding] = []
    for module in sorted(EXPECTED_MODULES - modules_seen):
        findings.append(
            Finding(
                id=f"coverage-{module}",
                case_id=case_id,
                pattern_id="coverage.missing_module",
                severity="info",
                title="Missing ExaWatcher module",
                summary=f"{module}.ExaWatcher was not found in this bundle.",
                module=module,
                timestamp="",
                entity_type="module",
                entity_name=module,
                metric_name="module_present",
                observed_value=0,
                threshold=1,
                unit="boolean",
                evidence_refs=[],
                kb_ids=match_kb("coverage.missing_module", kb_entries),
            )
        )
    return findings


def severity_for(pattern_id: str, observed: float, threshold: float) -> str:
    if pattern_id.startswith(("network", "roce", "cell")):
        return "critical"
    if threshold and observed >= threshold * 1.5:
        return "critical"
    if pattern_id == "memory.swap_activity":
        return "warning" if observed <= 10 else "critical"
    return "warning"


def title_for(pattern_id: str) -> str:
    return {
        "io.high_util": "High device utilization",
        "io.high_read_await": "Elevated read await",
        "io.high_write_await": "Elevated write await",
        "cpu.high_usage": "High CPU usage",
        "cpu.iowait": "Elevated CPU iowait",
        "cpu.softirq": "Elevated softirq CPU",
        "memory.swap_activity": "Swap activity detected",
        "network.error_signal": "Network error signal",
        "roce.error_signal": "RoCE error signal",
        "cell.error_signal": "Cell service error signal",
        "cell.latency_signal": "Cell latency signal",
        "cell.disk_state": "Cell disk state signal",
    }.get(pattern_id, pattern_id)


def format_unit(unit: str) -> str:
    if not unit:
        return ""
    if unit == "percent":
        return "%"
    return f" {unit}"
