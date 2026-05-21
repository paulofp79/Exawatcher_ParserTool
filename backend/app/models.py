from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MetricRow:
    case_id: str
    host: str
    module: str
    source_file: str
    timestamp: str
    entity_type: str
    entity_name: str
    metric_name: str
    value: float
    unit: str = ""
    raw_snippet_ref: str = ""


@dataclass
class EvidenceSnippet:
    ref: str
    source_file: str
    timestamp: str
    text: str


@dataclass
class Finding:
    id: str
    case_id: str
    pattern_id: str
    severity: str
    title: str
    summary: str
    module: str
    timestamp: str
    entity_type: str
    entity_name: str
    metric_name: str
    observed_value: float
    threshold: float
    unit: str
    evidence_refs: list[str] = field(default_factory=list)
    kb_ids: list[str] = field(default_factory=list)


@dataclass
class CaseMetadata:
    id: str
    name: str
    source_path: str
    imported_at: str
    host: str
    started_at: str
    ended_at: str
    metric_count: int
    finding_count: int
    modules: list[str]


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def row_to_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "__dataclass_fields__"):
        return {name: getattr(row, name) for name in row.__dataclass_fields__}
    return dict(row)
