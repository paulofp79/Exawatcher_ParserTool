from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - dependency fallback for parser-only tests
    yaml = None


@dataclass(slots=True)
class KnowledgeEntry:
    id: str
    title: str
    symptoms: list[str]
    matched_patterns: list[str]
    explanation: str
    recommended_checks: list[str]
    severity_guidance: str


def _fallback_parse(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    active_list: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("- id:"):
            if current:
                entries.append(current)
            current = {"id": line.split(":", 1)[1].strip().strip('"')}
            active_list = None
        elif current is not None and line.startswith("  ") and ":" in line and not line.lstrip().startswith("-"):
            key, value = line.strip().split(":", 1)
            value = value.strip().strip('"')
            if value:
                current[key] = value
                active_list = None
            else:
                current[key] = []
                active_list = key
        elif current is not None and active_list and line.strip().startswith("- "):
            current[active_list].append(line.strip()[2:].strip().strip('"'))
    if current:
        entries.append(current)
    return entries


def load_knowledge_base(path: Path) -> list[KnowledgeEntry]:
    text = path.read_text(encoding="utf-8")
    if yaml:
        raw_entries = yaml.safe_load(text) or []
    else:
        raw_entries = _fallback_parse(text)
    return [
        KnowledgeEntry(
            id=item["id"],
            title=item["title"],
            symptoms=list(item.get("symptoms", [])),
            matched_patterns=list(item.get("matched_patterns", [])),
            explanation=item.get("explanation", ""),
            recommended_checks=list(item.get("recommended_checks", [])),
            severity_guidance=item.get("severity_guidance", ""),
        )
        for item in raw_entries
    ]


def match_kb(pattern_id: str, entries: list[KnowledgeEntry]) -> list[str]:
    return [entry.id for entry in entries if pattern_id in entry.matched_patterns]

