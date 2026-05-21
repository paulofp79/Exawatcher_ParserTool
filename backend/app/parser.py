from __future__ import annotations

import json
import lzma
import re
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .models import EvidenceSnippet, MetricRow

SUPPORTED_MODULES = {
    "Iostat",
    "Mpstat",
    "Meminfo",
    "Vmstat",
    "Top",
    "TopPid",
    "Ps",
    "Netstat",
    "Rocestat",
    "Roceaudit",
    "IBCardInfo",
    "CellSrvStat",
    "CellSqlStat",
    "Cellmem",
    "Celldiskmd",
    "Diskinfo",
    "ECStat",
    "ECStatJSON",
}

EXPECTED_MODULES = SUPPORTED_MODULES
MAX_METRICS = 300_000
MODULE_PRIORITY = {
    "Iostat": 0,
    "Mpstat": 1,
    "Meminfo": 2,
    "Vmstat": 3,
    "Top": 4,
    "TopPid": 5,
    "Ps": 6,
    "Netstat": 7,
    "Rocestat": 8,
    "Roceaudit": 9,
    "IBCardInfo": 10,
    "CellSrvStat": 11,
    "CellSqlStat": 12,
    "Cellmem": 13,
    "Celldiskmd": 14,
    "Diskinfo": 15,
    "ECStat": 16,
    "ECStatJSON": 17,
}
HEADER_RE = re.compile(r"#\s*([^:]+):\s*(.*)")
HOST_RE = re.compile(r"\(([^)]+)\)")
ZZZ_RE = re.compile(r"zzz\s+<([^>]+)>")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2}\s+[AP]M)")
TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2}\s+[AP]M)")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class ParseResult:
    root_path: str
    host: str = ""
    started_at: str = ""
    ended_at: str = ""
    modules_seen: set[str] = field(default_factory=set)
    metrics: list[MetricRow] = field(default_factory=list)
    snippets: list[EvidenceSnippet] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_bundle(path: str) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Bundle path does not exist: {source}")
    if source.is_dir():
        return source, None
    if source.name.endswith(".tar.bz2"):
        temp = tempfile.TemporaryDirectory(prefix="exawatcher_")
        with tarfile.open(source, "r:bz2") as tar:
            tar.extractall(temp.name, filter="data")
        return Path(temp.name), temp
    raise ValueError("Import path must be an extracted directory or a .tar.bz2 archive")


def parse_bundle(path: str, case_id: str) -> ParseResult:
    root, temp = resolve_bundle(path)
    try:
        exa_root = find_exawatcher_root(root)
        result = ParseResult(root_path=str(exa_root))
        files = sorted(exa_root.rglob("*.dat.xz"), key=lambda p: (MODULE_PRIORITY.get(module_from_path(p), 99), str(p)))
        for file_path in files:
            module = module_from_path(file_path)
            if module not in SUPPORTED_MODULES:
                continue
            result.modules_seen.add(module)
            if len(result.metrics) >= MAX_METRICS:
                if not any("Metric cap reached" in warning for warning in result.warnings):
                    result.warnings.append(f"Metric cap reached at {MAX_METRICS:,} rows; later raw rows were skipped for interactive use.")
                continue
            try:
                parse_file(file_path, exa_root, module, case_id, result)
            except Exception as exc:  # keep partial imports useful
                result.warnings.append(f"{file_path.name}: {exc}")
        timestamps = sorted({m.timestamp for m in result.metrics if m.timestamp})
        if timestamps:
            result.started_at = timestamps[0]
            result.ended_at = timestamps[-1]
        return result
    finally:
        if temp:
            temp.cleanup()


def find_exawatcher_root(root: Path) -> Path:
    if any(child.name.endswith(".ExaWatcher") for child in root.iterdir() if child.is_dir()):
        return root
    candidates = [p for p in root.rglob("*") if p.is_dir() and p.name.startswith("ExaWatcher_")]
    for candidate in candidates:
        if any(child.name.endswith(".ExaWatcher") for child in candidate.iterdir() if child.is_dir()):
            return candidate
    return root


def module_from_path(path: Path) -> str:
    for parent in path.parents:
        if parent.name.endswith(".ExaWatcher"):
            return parent.name.split(".", 1)[0]
    return ""


def parse_file(path: Path, root: Path, module: str, case_id: str, result: ParseResult) -> None:
    lines = read_xz_lines(path)
    if not lines:
        return
    header = parse_header(lines[:20])
    current_ts = parse_any_timestamp(header.get("Starting Time", "")) or timestamp_from_filename(path.name)
    host = detect_host(lines, path.name)
    if host and not result.host:
        result.host = host
    source = str(path.relative_to(root))

    if module == "Iostat":
        parse_iostat(lines, case_id, result.host or host, module, source, current_ts, result)
    elif module == "Mpstat":
        parse_mpstat(lines, case_id, result.host or host, module, source, current_ts, result)
    elif module == "Meminfo":
        parse_key_value_module(lines, case_id, result.host or host, module, source, current_ts, result, "memory", kb_unit=True)
    elif module == "Vmstat":
        parse_vmstat(lines, case_id, result.host or host, module, source, current_ts, result)
    elif module in {"ECStatJSON"}:
        parse_ecstat_json(lines, case_id, result.host or host, module, source, current_ts, result)
    else:
        parse_signal_module(lines, case_id, result.host or host, module, source, current_ts, result)


def read_xz_lines(path: Path) -> list[str]:
    with lzma.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        return handle.readlines()


def parse_header(lines: Iterable[str]) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in lines:
        match = HEADER_RE.match(line.strip())
        if match:
            header[match.group(1).strip()] = match.group(2).strip()
    return header


def detect_host(lines: list[str], fallback: str) -> str:
    for line in lines[:40]:
        match = HOST_RE.search(line)
        if match and "." in match.group(1):
            return match.group(1)
    cleaned = fallback.removesuffix(".xz").removesuffix(".dat")
    parts = cleaned.split("_")
    return next((part for part in parts if "." in part), "")


def parse_any_timestamp(text: str, current_date: str | None = None) -> str:
    text = text.strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except ValueError:
            pass
    if current_date:
        try:
            return datetime.strptime(f"{current_date} {text}", "%m/%d/%Y %I:%M:%S %p").isoformat()
        except ValueError:
            pass
    return ""


def timestamp_from_filename(name: str) -> str:
    match = re.match(r"(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})", name)
    if not match:
        return ""
    y, mo, d, h, mi, s = match.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def add_metric(
    result: ParseResult,
    case_id: str,
    host: str,
    module: str,
    source_file: str,
    timestamp: str,
    entity_type: str,
    entity_name: str,
    metric_name: str,
    value: float,
    unit: str = "",
    raw: str = "",
) -> None:
    if len(result.metrics) >= MAX_METRICS:
        if not any("Metric cap reached" in warning for warning in result.warnings):
            result.warnings.append(f"Metric cap reached at {MAX_METRICS:,} rows; later raw rows were skipped for interactive use.")
        return
    snippet_ref = ""
    if raw:
        snippet_ref = f"s{len(result.snippets) + 1}"
        result.snippets.append(EvidenceSnippet(snippet_ref, source_file, timestamp, raw.strip()[:1200]))
    result.metrics.append(
        MetricRow(case_id, host, module, source_file, timestamp, entity_type, entity_name, metric_name, value, unit, snippet_ref)
    )


def parse_iostat(lines: list[str], case_id: str, host: str, module: str, source: str, current_ts: str, result: ParseResult) -> None:
    current_date = ""
    header: list[str] = []
    for line in lines:
        stripped = line.strip()
        date_match = DATE_RE.match(stripped)
        if date_match:
            current_date = date_match.group(1)
            current_ts = parse_any_timestamp(f"{date_match.group(1)} {date_match.group(2)}")
            continue
        if stripped.startswith("Device"):
            header = stripped.split()
            continue
        if not header or not stripped or stripped.startswith(("avg-cpu", "Linux", "#", "zzz")):
            continue
        parts = stripped.split()
        if len(parts) < len(header):
            continue
        device = parts[0]
        values = dict(zip(header[1:], parts[1:]))
        for metric in ("r/s", "w/s", "rMB/s", "wMB/s", "r_await", "w_await", "aqu-sz", "%util"):
            if metric in values and is_number(values[metric]):
                add_metric(result, case_id, host, module, source, current_ts, "device", device, metric, float(values[metric]), unit_for(metric), line)


def parse_mpstat(lines: list[str], case_id: str, host: str, module: str, source: str, current_ts: str, result: ParseResult) -> None:
    current_date = ""
    header: list[str] = []
    for line in lines:
        stripped = line.strip()
        if "\t" in line and "_x86_64_" in line:
            bits = line.split()
            if len(bits) >= 2:
                current_date = bits[-3] if "/" in bits[-3] else current_date
        if " CPU " in f" {stripped} " and "%idle" in stripped:
            header = stripped.split()
            if header[0].endswith("M"):
                header = header[1:]
            continue
        if not header or not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= len(header) + 1 and parts[1] in {"AM", "PM"}:
            ts_text = f"{parts[0]} {parts[1]}"
            current_ts = parse_any_timestamp(ts_text, current_date) or current_ts
            parts = parts[2:]
        if len(parts) < len(header):
            continue
        values = dict(zip(header, parts))
        cpu = values.get("CPU")
        if not cpu:
            continue
        for metric in ("%usr", "%sys", "%iowait", "%irq", "%soft", "%steal", "%idle"):
            if metric in values and is_number(values[metric]):
                add_metric(result, case_id, host, module, source, current_ts, "cpu", cpu, metric, float(values[metric]), "percent", line)


def parse_vmstat(lines: list[str], case_id: str, host: str, module: str, source: str, current_ts: str, result: ParseResult) -> None:
    header: list[str] = []
    for line in lines:
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            current_ts = parse_any_timestamp(zzz.group(1)) or current_ts
        if stripped.startswith("r ") or stripped.startswith("procs"):
            header = stripped.split()
            continue
        parts = stripped.split()
        if not header or len(parts) < len(header) or not all(is_number(p) for p in parts[: min(4, len(parts))]):
            continue
        values = dict(zip(header, parts))
        for metric in ("r", "b", "swpd", "free", "si", "so", "us", "sy", "id", "wa", "st"):
            if metric in values and is_number(values[metric]):
                unit = "kb" if metric in {"swpd", "free"} else "count"
                add_metric(result, case_id, host, module, source, current_ts, "system", "vmstat", metric, float(values[metric]), unit, line)


def parse_key_value_module(
    lines: list[str],
    case_id: str,
    host: str,
    module: str,
    source: str,
    current_ts: str,
    result: ParseResult,
    entity_type: str,
    kb_unit: bool = False,
) -> None:
    for line in lines:
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            current_ts = parse_any_timestamp(zzz.group(1)) or current_ts
            continue
        if ":" not in stripped:
            continue
        key, value_text = stripped.split(":", 1)
        number = NUMBER_RE.search(value_text)
        if not number:
            continue
        value = float(number.group(0))
        unit = "kb" if kb_unit and "kb" in value_text.lower() else ""
        add_metric(result, case_id, host, module, source, current_ts, entity_type, "system", key.strip(), value, unit, line)


def parse_ecstat_json(lines: list[str], case_id: str, host: str, module: str, source: str, current_ts: str, result: ParseResult) -> None:
    text = "".join(line for line in lines if not line.startswith("#") and not line.startswith("zzz "))
    start = text.find("{")
    if start < 0:
        parse_signal_module(lines, case_id, host, module, source, current_ts, result)
        return
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        parse_signal_module(lines, case_id, host, module, source, current_ts, result)
        return
    walk_json_metrics(data, case_id, host, module, source, current_ts, result)


def walk_json_metrics(value: object, case_id: str, host: str, module: str, source: str, fallback_ts: str, result: ParseResult, prefix: str = "") -> None:
    if isinstance(value, dict):
        ts = parse_any_timestamp(str(value.get("timestampFormatted", ""))) or fallback_ts
        entity = str(value.get("name") or value.get("deviceName") or prefix or "cell")
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                walk_json_metrics(child, case_id, host, module, source, ts, result, f"{prefix}.{key}" if prefix else key)
            elif isinstance(child, (int, float)) and key not in {"timestamp"}:
                add_metric(result, case_id, host, module, source, ts, "cell", entity, f"{prefix}.{key}" if prefix else key, float(child), "", f"{key}: {child}")
    elif isinstance(value, list):
        for child in value:
            walk_json_metrics(child, case_id, host, module, source, fallback_ts, result, prefix)


def parse_signal_module(lines: list[str], case_id: str, host: str, module: str, source: str, current_ts: str, result: ParseResult) -> None:
    for line in lines:
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            current_ts = parse_any_timestamp(zzz.group(1)) or current_ts
            continue
        lower = stripped.lower()
        if any(token in lower for token in ("error", "fail", "offline", "drop", "retrans", "timeout", "latency")):
            nums = [float(n) for n in NUMBER_RE.findall(stripped)]
            value = nums[-1] if nums else 1.0
            add_metric(result, case_id, host, module, source, current_ts, "signal", module, "signal", value, "count", line)


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def unit_for(metric: str) -> str:
    if metric.startswith("%"):
        return "percent"
    if metric.endswith("MB/s"):
        return "MB/s"
    if "await" in metric:
        return "ms"
    if metric.endswith("/s"):
        return "ops/s"
    return ""
