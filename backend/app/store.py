from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .models import CaseMetadata, EvidenceSnippet, Finding, MetricRow, row_to_dict


class Store:
    def __init__(self, db_path: Path, cases_dir: Path):
        self.db_path = db_path
        self.cases_dir = cases_dir
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists cases (
                    id text primary key,
                    name text not null,
                    source_path text not null,
                    imported_at text not null,
                    host text,
                    started_at text,
                    ended_at text,
                    metric_count integer not null,
                    finding_count integer not null,
                    modules_json text not null
                );
                create table if not exists metrics (
                    case_id text not null,
                    host text,
                    module text,
                    source_file text,
                    timestamp text,
                    entity_type text,
                    entity_name text,
                    metric_name text,
                    value real,
                    unit text,
                    raw_snippet_ref text
                );
                create index if not exists idx_metrics_case_module on metrics(case_id, module, metric_name);
                create index if not exists idx_metrics_case_time on metrics(case_id, timestamp);
                create table if not exists snippets (
                    case_id text not null,
                    ref text not null,
                    source_file text,
                    timestamp text,
                    text text,
                    primary key(case_id, ref)
                );
                create table if not exists findings (
                    id text not null,
                    case_id text not null,
                    pattern_id text,
                    severity text,
                    title text,
                    summary text,
                    module text,
                    timestamp text,
                    entity_type text,
                    entity_name text,
                    metric_name text,
                    observed_value real,
                    threshold real,
                    unit text,
                    evidence_refs_json text,
                    kb_ids_json text,
                    primary key(case_id, id)
                );
                create table if not exists prompt_packets (
                    case_id text primary key,
                    packet_json text not null
                );
                """
            )

    def save_case(
        self,
        case: CaseMetadata,
        metrics: list[MetricRow],
        snippets: list[EvidenceSnippet],
        findings: list[Finding],
        prompt_packet: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute("delete from cases where id = ?", (case.id,))
            conn.execute("delete from metrics where case_id = ?", (case.id,))
            conn.execute("delete from snippets where case_id = ?", (case.id,))
            conn.execute("delete from findings where case_id = ?", (case.id,))
            conn.execute("delete from prompt_packets where case_id = ?", (case.id,))
            conn.execute(
                """
                insert into cases values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.id,
                    case.name,
                    case.source_path,
                    case.imported_at,
                    case.host,
                    case.started_at,
                    case.ended_at,
                    case.metric_count,
                    case.finding_count,
                    json.dumps(case.modules),
                ),
            )
            conn.executemany(
                """
                insert into metrics values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        m.case_id,
                        m.host,
                        m.module,
                        m.source_file,
                        m.timestamp,
                        m.entity_type,
                        m.entity_name,
                        m.metric_name,
                        m.value,
                        m.unit,
                        m.raw_snippet_ref,
                    )
                    for m in metrics
                ],
            )
            conn.executemany(
                "insert into snippets values (?, ?, ?, ?, ?)",
                [(case.id, s.ref, s.source_file, s.timestamp, s.text) for s in snippets],
            )
            conn.executemany(
                """
                insert into findings values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f.id,
                        f.case_id,
                        f.pattern_id,
                        f.severity,
                        f.title,
                        f.summary,
                        f.module,
                        f.timestamp,
                        f.entity_type,
                        f.entity_name,
                        f.metric_name,
                        f.observed_value,
                        f.threshold,
                        f.unit,
                        json.dumps(f.evidence_refs),
                        json.dumps(f.kb_ids),
                    )
                    for f in findings
                ],
            )
            conn.execute("insert into prompt_packets values (?, ?)", (case.id, json.dumps(prompt_packet, indent=2)))

    def list_cases(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("select * from cases order by imported_at desc").fetchall()
        return [case_from_row(row) for row in rows]

    def get_case(self, case_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("select * from cases where id = ?", (case_id,)).fetchone()
        return case_from_row(row) if row else None

    def get_metrics(self, case_id: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from metrics
                where case_id = ?
                order by timestamp, module, entity_name, metric_name
                limit ?
                """,
                (case_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_findings(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                select * from findings
                where case_id = ?
                order by
                  case severity
                    when 'critical' then 1
                    when 'warning' then 2
                    else 3
                  end,
                  timestamp
                """,
                (case_id,),
            ).fetchall()
        findings = []
        for row in rows:
            item = dict(row)
            item["evidence_refs"] = json.loads(item.pop("evidence_refs_json") or "[]")
            item["kb_ids"] = json.loads(item.pop("kb_ids_json") or "[]")
            findings.append(item)
        return findings

    def get_snippets(self, case_id: str, refs: Optional[list[str]] = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if refs:
                placeholders = ",".join("?" for _ in refs)
                rows = conn.execute(
                    f"select ref, source_file, timestamp, text from snippets where case_id = ? and ref in ({placeholders})",
                    [case_id, *refs],
                ).fetchall()
            else:
                rows = conn.execute("select ref, source_file, timestamp, text from snippets where case_id = ?", (case_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_prompt_packet(self, case_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("select packet_json from prompt_packets where case_id = ?", (case_id,)).fetchone()
        return json.loads(row["packet_json"]) if row else None


def case_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["modules"] = json.loads(item.pop("modules_json") or "[]")
    return item


def build_prompt_packet(
    case: CaseMetadata,
    findings: list[Finding],
    snippets: list[EvidenceSnippet],
    kb_entries: list[Any],
    warnings: list[str],
) -> dict[str, Any]:
    snippet_map = {s.ref: row_to_dict(s) for s in snippets}
    kb_map = {entry.id: row_to_dict(entry) for entry in kb_entries}
    top_findings = findings[:50]
    packet = {
        "case": row_to_dict(case),
        "warnings": warnings,
        "summary_instruction": (
            "Write a concise Exadata Storage Cell troubleshooting summary. Prioritize critical findings, "
            "cite timestamps/source modules, explain likely impact, and list recommended next checks."
        ),
        "findings": [row_to_dict(f) for f in top_findings],
        "evidence_snippets": {
            ref: snippet_map[ref]
            for finding in top_findings
            for ref in finding.evidence_refs
            if ref in snippet_map
        },
        "knowledge_base_matches": {
            kb_id: kb_map[kb_id]
            for finding in top_findings
            for kb_id in finding.kb_ids
            if kb_id in kb_map
        },
    }
    packet["prompt"] = render_prompt(packet)
    return packet


def render_prompt(packet: dict[str, Any]) -> str:
    case = packet["case"]
    lines = [
        "You are analyzing Exadata Storage Cell ExaWatcher output.",
        f"Case: {case['name']} ({case['id']})",
        f"Host: {case.get('host') or 'unknown'}",
        f"Window: {case.get('started_at') or 'unknown'} to {case.get('ended_at') or 'unknown'}",
        "",
        packet["summary_instruction"],
        "",
        "Findings:",
    ]
    for finding in packet["findings"][:25]:
        lines.append(
            f"- [{finding['severity']}] {finding['title']} at {finding['timestamp']} "
            f"({finding['module']} {finding['entity_name']} {finding['metric_name']}={finding['observed_value']}{finding['unit']})"
        )
        lines.append(f"  Evidence refs: {', '.join(finding['evidence_refs']) or 'none'}")
        lines.append(f"  KB refs: {', '.join(finding['kb_ids']) or 'none'}")
    lines.extend(["", "Relevant evidence snippets:"])
    for ref, snippet in packet["evidence_snippets"].items():
        lines.append(f"- {ref} {snippet['source_file']} {snippet['timestamp']}: {snippet['text']}")
    lines.extend(["", "Knowledge base guidance:"])
    for kb_id, entry in packet["knowledge_base_matches"].items():
        lines.append(f"- {kb_id}: {entry['title']} - {entry['explanation']}")
    return "\n".join(lines)
