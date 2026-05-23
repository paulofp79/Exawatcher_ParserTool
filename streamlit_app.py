from __future__ import annotations

import json
import lzma
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import streamlit as st


DEFAULT_PATH = "/root/PP/ExaWatcher_gru126171exdcl18.oraclecloud.internal_2026-05-13_19_00_00_3h00m00s"
HEADER_RE = re.compile(r"#\s*([^:]+):\s*(.*)")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2}\s+[AP]M)")
ZZZ_RE = re.compile(r"zzz\s+<([^>]+)>")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
SIGNAL_WORDS = ("error", "fail", "offline", "drop", "dropped", "retrans", "timeout", "latency", "corrupt")


@dataclass
class ToolSummary:
    tool: str
    path: str
    file_count: int = 0
    xz_count: int = 0
    size_mb: float = 0.0
    first_time: str = ""
    last_time: str = ""
    commands: List[str] = field(default_factory=list)
    versions: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)


def main() -> None:
    st.set_page_config(page_title="ExaWatcher Workbench", layout="wide")
    st.title("ExaWatcher Workbench")

    with st.sidebar:
        st.header("Source")
        root_text = st.text_input("ExaWatcher directory", value=DEFAULT_PATH)
        max_rows = st.slider("Rows per tool", 5_000, 100_000, 30_000, step=5_000)
        load = st.button("Scan / Refresh", type="primary")
        st.caption("This Streamlit version reads the ExaWatcher files directly on the server.")

    if load:
        st.cache_data.clear()

    root = find_exawatcher_root(Path(root_text).expanduser())
    if not root or not root.exists():
        st.error(f"Path not found or not an ExaWatcher directory: {root_text}")
        return

    summaries = scan_tools(str(root))
    if not summaries:
        st.error(f"No *.ExaWatcher tool directories found under: {root}")
        return

    first_time = min([s.first_time for s in summaries if s.first_time] or [""])
    last_time = max([s.last_time for s in summaries if s.last_time] or [""])
    total_files = sum(s.file_count for s in summaries)
    total_size = sum(s.size_mb for s in summaries)

    st.caption(str(root))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tools gathered", len(summaries))
    c2.metric("Files", f"{total_files:,}")
    c3.metric("Size", f"{total_size:,.1f} MB")
    c4.metric("Period", f"{first_time or '?'} to {last_time or '?'}")

    tab_names = ["Summary", "Problems"] + [s.tool for s in summaries]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_summary(summaries)

    with tabs[1]:
        render_problems(root, summaries, max_rows)

    for tab, summary in zip(tabs[2:], summaries):
        with tab:
            render_tool_tab(root, summary, max_rows)


def find_exawatcher_root(path: Path) -> Optional[Path]:
    if path.exists() and path.is_dir() and any(child.name.endswith(".ExaWatcher") for child in path.iterdir() if child.is_dir()):
        return path
    if path.exists() and path.is_dir():
        for candidate in path.rglob("ExaWatcher_*"):
            if candidate.is_dir() and any(child.name.endswith(".ExaWatcher") for child in candidate.iterdir() if child.is_dir()):
                return candidate
    return path


def tool_name(path: Path) -> str:
    if path.name.endswith(".ExaWatcher"):
        return path.name.split(".", 1)[0]
    if path.name.startswith("Charts.ExaWatcher"):
        return "Charts"
    return path.name


@st.cache_data(show_spinner=False)
def scan_tools(root_text: str) -> List[ToolSummary]:
    root = Path(root_text)
    summaries: List[ToolSummary] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not (child.name.endswith(".ExaWatcher") or child.name.startswith("Charts.ExaWatcher")):
            continue
        files = sorted(path for path in child.rglob("*") if path.is_file())
        xz_files = [path for path in files if path.name.endswith(".xz")]
        summary = ToolSummary(
            tool=tool_name(child),
            path=str(child.relative_to(root)),
            file_count=len(files),
            xz_count=len(xz_files),
            size_mb=sum(path.stat().st_size for path in files) / 1024 / 1024,
            files=[str(path.relative_to(root)) for path in files[:200]],
        )
        times: List[str] = []
        for file_path in xz_files:
            ts = timestamp_from_filename(file_path.name)
            if ts:
                times.append(ts)
            header = read_header(file_path)
            started = parse_any_timestamp(header.get("Starting Time", ""))
            if started:
                times.append(started)
            command = header.get("Collection Command", "")
            if command and command not in summary.commands:
                summary.commands.append(command)
            version = header.get("Version", "")
            if version and version not in summary.versions:
                summary.versions.append(version)
        summary.first_time = min(times) if times else ""
        summary.last_time = max(times) if times else ""
        summaries.append(summary)
    return summaries


def render_summary(summaries: List[ToolSummary]) -> None:
    st.subheader("Gathered tools")
    rows = [
        {
            "Tool": s.tool,
            "Files": s.file_count,
            "Compressed files": s.xz_count,
            "Size MB": round(s.size_mb, 2),
            "First sample": s.first_time,
            "Last sample": s.last_time,
            "Command": " ; ".join(s.commands[:2]),
            "Version": ", ".join(s.versions[:3]),
        }
        for s in summaries
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_tool_tab(root: Path, summary: ToolSummary, max_rows: int) -> None:
    st.subheader(summary.tool)
    st.write(f"**Files:** {summary.file_count:,}  **Compressed:** {summary.xz_count:,}  **Period:** {summary.first_time or '?'} to {summary.last_time or '?'}")
    if summary.commands:
        st.code("\n".join(summary.commands), language="bash")

    with st.expander("Files in this tool", expanded=False):
        st.dataframe(pd.DataFrame({"file": summary.files}), use_container_width=True, hide_index=True)

    if summary.xz_count == 0:
        st.info("No compressed .xz data files found for this tool.")
        return

    load_key = f"loaded_{summary.tool}"
    if st.button(f"Load data for {summary.tool}", key=f"load_{summary.tool}"):
        st.session_state[load_key] = True
    if not st.session_state.get(load_key, False):
        st.info("Click Load data to parse this tool and enable charting. File counts and collection period are already shown above.")
        return

    df = parse_tool(str(root), summary.path, max_rows)
    if df.empty:
        st.warning("No chartable numeric rows were parsed for this tool yet. The file count above still confirms it was gathered.")
        render_raw_preview(root, summary)
        return

    metric_names = sorted(df["metric"].dropna().unique().tolist())
    entity_names = sorted(df["entity"].dropna().unique().tolist())

    c1, c2 = st.columns([1, 2])
    metric = c1.selectbox("Metric", metric_names, key=f"metric_{summary.tool}")
    default_entities = entity_names[: min(8, len(entity_names))]
    entities = c2.multiselect("Entities", entity_names, default=default_entities, key=f"entity_{summary.tool}")

    chart_df = df[df["metric"] == metric].copy()
    if entities:
        chart_df = chart_df[chart_df["entity"].isin(entities)]

    if chart_df.empty:
        st.info("No rows match the current metric/entity selection.")
    else:
        pivot = chart_df.pivot_table(index="timestamp", columns="entity", values="value", aggfunc="mean").sort_index()
        st.line_chart(pivot, use_container_width=True)

    st.dataframe(
        chart_df[["timestamp", "entity", "metric", "value", "unit", "source"]].head(1000),
        use_container_width=True,
        hide_index=True,
    )


def render_problems(root: Path, summaries: List[ToolSummary], max_rows: int) -> None:
    st.subheader("Problem summary")
    if st.button("Analyze gathered tools", type="primary"):
        problems: List[Dict[str, Any]] = []
        progress = st.progress(0, text="Analyzing tools...")
        for idx, summary in enumerate(summaries):
            df = parse_tool(str(root), summary.path, min(max_rows, 30_000))
            problems.extend(detect_numeric_problems(summary.tool, df))
            problems.extend(scan_signal_problems(root, summary))
            progress.progress((idx + 1) / len(summaries), text=f"Analyzed {summary.tool}")
        progress.empty()
        st.session_state["problems"] = problems

    problems = st.session_state.get("problems", [])
    if not problems:
        st.info("Click Analyze gathered tools to parse metrics and summarize critical, warning, and info findings.")
        return

    problem_df = pd.DataFrame(problems)
    c1, c2, c3 = st.columns(3)
    c1.metric("Critical", int((problem_df["severity"] == "critical").sum()))
    c2.metric("Warning", int((problem_df["severity"] == "warning").sum()))
    c3.metric("Info", int((problem_df["severity"] == "info").sum()))
    st.dataframe(problem_df, use_container_width=True, hide_index=True)


@st.cache_data(show_spinner=False)
def parse_tool(root_text: str, relative_tool_path: str, max_rows: int) -> pd.DataFrame:
    root = Path(root_text)
    tool_dir = root / relative_tool_path
    module = tool_name(tool_dir)
    rows: List[Dict[str, Any]] = []
    for file_path in sorted(tool_dir.rglob("*.xz")):
        if len(rows) >= max_rows:
            break
        text_rows = read_lines(file_path, max_lines=250_000)
        if module == "Iostat":
            rows.extend(parse_iostat(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "Mpstat":
            rows.extend(parse_mpstat(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "Vmstat":
            rows.extend(parse_vmstat(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "Meminfo":
            rows.extend(parse_key_values(text_rows, file_path, root, module, max_rows - len(rows)))
        elif module == "ECStatJSON":
            rows.extend(parse_json_metrics(text_rows, file_path, root, module, max_rows - len(rows)))
        else:
            rows.extend(parse_key_values(text_rows, file_path, root, module, max_rows - len(rows)))
            if len(rows) < max_rows:
                rows.extend(parse_generic_tables(text_rows, file_path, root, module, max_rows - len(rows)))
    if not rows:
        return pd.DataFrame(columns=["timestamp", "entity", "metric", "value", "unit", "source"])
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    return df.sort_values(["timestamp", "entity", "metric"])


def read_header(path: Path) -> Dict[str, str]:
    header: Dict[str, str] = {}
    for line in read_lines(path, max_lines=40):
        match = HEADER_RE.match(line.strip())
        if match:
            header[match.group(1).strip()] = match.group(2).strip()
    return header


def read_lines(path: Path, max_lines: int) -> List[str]:
    opener = lzma.open if path.name.endswith(".xz") else open
    lines: List[str] = []
    try:
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if idx >= max_lines:
                    break
                lines.append(line.rstrip("\n"))
    except Exception as exc:
        return [f"# read error: {exc}"]
    return lines


def parse_iostat(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    header: List[str] = []
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        date_match = DATE_RE.match(stripped)
        if date_match:
            timestamp = parse_any_timestamp(f"{date_match.group(1)} {date_match.group(2)}") or timestamp
            continue
        if stripped.startswith("Device"):
            header = stripped.split()
            continue
        if not header or not stripped or stripped.startswith(("avg-cpu", "Linux", "#", "zzz")):
            continue
        parts = stripped.split()
        if len(parts) < len(header):
            continue
        entity = parts[0]
        values = dict(zip(header[1:], parts[1:]))
        rows.extend(long_rows(timestamp, entity, values, path, root, ""))
    return rows[:limit]


def parse_mpstat(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    current_date = ""
    header: List[str] = []
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        if "_x86_64_" in line:
            bits = line.split()
            current_date = next((bit for bit in bits if "/" in bit), current_date)
        if " CPU " in f" {stripped} " and "%idle" in stripped:
            header = stripped.split()
            if header and header[0].endswith("M"):
                header = header[1:]
            continue
        parts = stripped.split()
        if not header or len(parts) < len(header):
            continue
        if len(parts) >= len(header) + 1 and parts[1] in {"AM", "PM"}:
            timestamp = parse_any_timestamp(f"{parts[0]} {parts[1]}", current_date) or timestamp
            parts = parts[2:]
        values = dict(zip(header, parts))
        entity = values.pop("CPU", "")
        if entity:
            rows.extend(long_rows(timestamp, entity, values, path, root, "percent"))
    return rows[:limit]


def parse_vmstat(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    header: List[str] = []
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            timestamp = parse_any_timestamp(zzz.group(1)) or timestamp
            continue
        if stripped.startswith("r "):
            header = stripped.split()
            continue
        parts = stripped.split()
        if not header or len(parts) < len(header) or not is_number(parts[0]):
            continue
        rows.extend(long_rows(timestamp, "vmstat", dict(zip(header, parts)), path, root, ""))
    return rows[:limit]


def parse_key_values(lines: List[str], path: Path, root: Path, module: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            timestamp = parse_any_timestamp(zzz.group(1)) or timestamp
            continue
        if ":" not in stripped:
            continue
        key, value_text = stripped.split(":", 1)
        number = NUMBER_RE.search(value_text)
        if not number:
            continue
        rows.append(row(timestamp, module, key.strip(), float(number.group(0)), infer_unit(key, value_text), path, root))
    return rows


def parse_json_metrics(lines: List[str], path: Path, root: Path, module: str, limit: int) -> List[Dict[str, Any]]:
    text = "\n".join(line for line in lines if not line.startswith("#") and not line.startswith("zzz "))
    start = text.find("{")
    if start < 0:
        return []
    try:
        data = json.loads(text[start:])
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    walk_json(data, rows, timestamp_from_filename(path.name), "cell", "", path, root, limit)
    return rows


def walk_json(value: Any, rows: List[Dict[str, Any]], timestamp: str, entity: str, prefix: str, path: Path, root: Path, limit: int) -> None:
    if len(rows) >= limit:
        return
    if isinstance(value, dict):
        timestamp = parse_any_timestamp(str(value.get("timestampFormatted", ""))) or timestamp
        entity = str(value.get("name") or value.get("deviceName") or entity)
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(child, (dict, list)):
                walk_json(child, rows, timestamp, entity, next_prefix, path, root, limit)
            elif isinstance(child, (int, float)) and key != "timestamp":
                rows.append(row(timestamp, entity, next_prefix, float(child), "", path, root))
    elif isinstance(value, list):
        for child in value:
            walk_json(child, rows, timestamp, entity, prefix, path, root, limit)


def parse_generic_tables(lines: List[str], path: Path, root: Path, module: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    header: List[str] = []
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            timestamp = parse_any_timestamp(zzz.group(1)) or timestamp
            continue
        if not stripped or stripped.startswith(("#", "Linux", "zzz")):
            continue
        parts = stripped.split()
        numeric = [is_number(part) for part in parts]
        if len(parts) >= 3 and not any(numeric) and any(any(ch.isalpha() for ch in part) for part in parts):
            header = parts
            continue
        if not header or not any(numeric):
            continue
        entity = parts[0]
        for idx, value_text in enumerate(parts):
            if idx == 0 or not is_number(value_text):
                continue
            metric = header[idx] if idx < len(header) else f"col_{idx}"
            rows.append(row(timestamp, entity, metric, float(value_text), infer_unit(metric, ""), path, root))
    return rows[:limit]


def long_rows(timestamp: str, entity: str, values: Dict[str, str], path: Path, root: Path, default_unit: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for metric, value_text in values.items():
        if is_number(value_text):
            output.append(row(timestamp, entity, metric, float(value_text), infer_unit(metric, "") or default_unit, path, root))
    return output


def row(timestamp: str, entity: str, metric: str, value: float, unit: str, path: Path, root: Path) -> Dict[str, Any]:
    return {
        "timestamp": timestamp,
        "entity": entity,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source": str(path.relative_to(root)),
    }


def detect_numeric_problems(module: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    problems: List[Dict[str, Any]] = []
    checks = [
        ("%util", 90, "critical", "High device utilization"),
        ("%util", 80, "warning", "Elevated device utilization"),
        ("r_await", 50, "critical", "High read await"),
        ("r_await", 20, "warning", "Elevated read await"),
        ("w_await", 100, "critical", "High write await"),
        ("w_await", 50, "warning", "Elevated write await"),
        ("%iowait", 30, "critical", "High CPU iowait"),
        ("%iowait", 15, "warning", "Elevated CPU iowait"),
        ("%soft", 30, "warning", "Elevated softirq CPU"),
        ("si", 0, "warning", "Swap-in activity"),
        ("so", 0, "warning", "Swap-out activity"),
    ]
    for metric, threshold, severity, title in checks:
        subset = df[(df["metric"] == metric) & (df["value"] > threshold)]
        if subset.empty:
            continue
        worst = subset.sort_values("value", ascending=False).iloc[0]
        problems.append(
            {
                "severity": severity,
                "tool": module,
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst["entity"],
                "metric": metric,
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
            }
        )
    if module == "Mpstat":
        subset = df[(df["entity"] == "all") & (df["metric"] == "%idle")]
        if not subset.empty:
            worst = subset.sort_values("value").iloc[0]
            usage = 100 - float(worst["value"])
            if usage > 90:
                severity = "critical"
            elif usage > 80:
                severity = "warning"
            else:
                severity = ""
            if severity:
                problems.append(
                    {
                        "severity": severity,
                        "tool": module,
                        "title": "High CPU usage",
                        "time": str(worst["timestamp"]),
                        "entity": "all",
                        "metric": "100 - %idle",
                        "value": round(usage, 3),
                        "source": worst["source"],
                    }
                )
    return problems


def scan_signal_problems(root: Path, summary: ToolSummary) -> List[Dict[str, Any]]:
    problems: List[Dict[str, Any]] = []
    tool_dir = root / summary.path
    for file_path in sorted(tool_dir.rglob("*.xz"))[:3]:
        timestamp = timestamp_from_filename(file_path.name)
        for line in read_lines(file_path, max_lines=5000):
            lower = line.lower()
            if any(word in lower for word in SIGNAL_WORDS):
                problems.append(
                    {
                        "severity": "info",
                        "tool": summary.tool,
                        "title": "Signal word in output",
                        "time": timestamp,
                        "entity": "",
                        "metric": "",
                        "value": "",
                        "source": str(file_path.relative_to(root)),
                        "detail": line[:240],
                    }
                )
                break
    return problems


def render_raw_preview(root: Path, summary: ToolSummary) -> None:
    files = sorted((root / summary.path).rglob("*.xz"))
    if not files:
        return
    with st.expander("Raw preview"):
        preview = "\n".join(read_lines(files[0], max_lines=80))
        st.code(preview[:8000])


def timestamp_from_filename(name: str) -> str:
    match = re.match(r"(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})", name)
    if not match:
        return ""
    y, mo, d, h, mi, s = match.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}"


def parse_any_timestamp(text: str, current_date: Optional[str] = None) -> str:
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


def is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except Exception:
        return False


def infer_unit(metric: str, value_text: str) -> str:
    lower = f"{metric} {value_text}".lower()
    if metric.startswith("%"):
        return "percent"
    if "await" in lower or "lat" in lower:
        return "ms"
    if "kb" in lower:
        return "kb"
    if "mb/s" in lower:
        return "MB/s"
    if metric.endswith("/s"):
        return "per_sec"
    return ""


if __name__ == "__main__":
    main()
