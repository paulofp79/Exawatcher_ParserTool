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
CELLMEM_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)")
SIGNAL_WORDS = ("error", "fail", "offline", "drop", "dropped", "retrans", "timeout", "latency", "corrupt")
EXCLUDED_TOOLS = {"Celldiskmd"}
CELL_SQLSTAT_DESCRIPTIONS = {
    "CDBID": "Container database ID running the SQL query",
    "DBID": "Database ID running the SQL query",
    "SQLID": "SQL ID of the SQL query",
    "Duration Seconds": "Aggregated run time across all runs, converted to seconds",
    "Memory Bytes": "Amount of offload server memory used by the SQL statement",
    "%CPU": "Percentage of elapsed time spent on CPU; can exceed 100% for multiple threads",
    "Requested Bytes": "Bytes eligible for smart scan",
    "Returned Bytes": "Bytes returned to the database by smart scan",
    "%Storage Index": "Percentage of requested bytes saved by storage index",
    "%XRMEM Columnar": "Percentage of requested bytes read from XRMEM columnar cache",
    "%Flash Columnar": "Percentage of requested bytes read from flash columnar cache",
    "%Flash Regular": "Percentage of requested bytes read from flash cache, non-columnar",
    "%Disk": "Percentage of requested bytes read from disk",
    "%Passthru": "Percentage of requested bytes returned directly to the database with no offloading",
    "XRMEM Columnar Bytes": "Physical bytes read from XRMEM columnar cache",
    "Flash Columnar Bytes": "Physical bytes read from flash columnar cache",
    "Flash Regular Bytes": "Physical bytes read from flash cache, non-columnar",
    "Disk Bytes": "Physical bytes read from disk",
    "Columnar Saved Bytes": "Physical bytes saved by flash columnar cache and XRMEM columnar cache",
    "Storage Index Saved Bytes": "Requested Bytes saved by storage index",
    "Passthru Bytes": "Requested bytes returned directly to the database with no offloading",
    "IOs": "Smart IOs completed since start of query",
    "DBNAME": "Database name running the SQL query",
}
CELL_SQLSTAT_PERCENT_FIELDS = [
    "%Storage Index",
    "%XRMEM Columnar",
    "%Flash Columnar",
    "%Flash Regular",
    "%Disk",
    "%Passthru",
]
CELL_SQLSTAT_BYTE_FIELDS = [
    "XRMEM Columnar Bytes",
    "Flash Columnar Bytes",
    "Flash Regular Bytes",
    "Disk Bytes",
    "Columnar Saved Bytes",
    "Storage Index Saved Bytes",
    "Passthru Bytes",
]
CELL_SRVSTAT_DESCRIPTIONS = {
    "Input/Output related stats": "CellSrv I/O counters, queueing, latency warnings, per-disk utilization, pending I/O, and FlashCache counters.",
    "Memory related stats": "SGA/PGA/cellsrv/kernel memory allocation and top memory consumers.",
    "Execution related stats": "CellSrv job execution, thread waits, buffer pressure, predicate/offload scheduling, and CPU scheduling ratios.",
}
CELL_MEM_FIELDS = [
    ("%OS_AVAIL", "percent", "OS availability", "Percentage of operating system memory available."),
    ("OS_AVAIL", "GB", "OS availability", "Operating system memory available."),
    ("OS_TOT", "GB", "OS availability", "Total operating system memory."),
    ("OS_USR", "GB", "OS usage", "Operating system memory used by user space."),
    ("OS_KNL", "GB", "OS usage", "Operating system memory used by kernel space."),
    ("SLAB", "GB", "Kernel breakdown", "Kernel slab memory."),
    ("RDS", "GB", "Kernel breakdown", "RDS memory."),
    ("RDMA", "GB", "Kernel breakdown", "RDMA memory."),
    ("PGST", "GB", "Kernel breakdown", "Page store memory."),
    ("OFLPTE", "GB", "Kernel breakdown", "Offload page table entry memory."),
    ("OTHER", "GB", "Kernel breakdown", "Other kernel memory."),
    ("%CL_AVAIL", "percent", "Cell availability", "Percentage of cell memory available."),
    ("CL_AVAIL", "GB", "Cell availability", "Cell memory available."),
    ("CL_MAX", "GB", "Cell limits", "Maximum cell memory after reserved memory."),
    ("CL_MAX_OS_TOT", "GB", "Cell limits", "OS total memory used in the cell max formula."),
    ("CL_RVD", "GB", "Cell limits", "Cell reserved memory."),
    ("CL_USD", "GB", "Cell usage", "Cell memory used."),
    ("CL_C", "GB", "Cell usage", "Cell memory used by C component."),
    ("CL_O", "GB", "Cell usage", "Cell memory used by O component."),
    ("CL_K", "GB", "Cell usage", "Cell memory used by K component."),
    ("OTHER_SERVICES", "GB", "Cell usage", "Memory used by other services."),
]


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
        if tool_name(child) in EXCLUDED_TOOLS:
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

    if summary.tool == "CellSqlStat":
        render_cellsqlstat(df)
        return
    if summary.tool == "CellSrvStat":
        render_cellsrvstat(df)
        return
    if summary.tool == "Cellmem":
        render_cellmem(df)
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
        elif module == "Cellmem":
            rows.extend(parse_cellmem(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "ECStatJSON":
            rows.extend(parse_json_metrics(text_rows, file_path, root, module, max_rows - len(rows)))
        elif module == "CellSqlStat":
            rows.extend(parse_cellsqlstat(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "CellSrvStat":
            rows.extend(parse_cellsrvstat(text_rows, file_path, root, max_rows - len(rows)))
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


def render_cellsqlstat(df: pd.DataFrame) -> None:
    with st.expander("CellSqlStat column legend", expanded=False):
        legend = [{"Column": key, "Description": value} for key, value in CELL_SQLSTAT_DESCRIPTIONS.items()]
        st.dataframe(pd.DataFrame(legend), use_container_width=True, hide_index=True)

    metric_names = sorted(df["metric"].dropna().unique().tolist())
    if not metric_names:
        st.info("No CellSqlStat numeric metrics were parsed.")
        return
    sqlids = sorted(df["sqlid"].dropna().unique().tolist()) if "sqlid" in df.columns else sorted(df["entity"].dropna().unique().tolist())
    default_metric = "Memory Bytes" if "Memory Bytes" in metric_names else metric_names[0]
    c1, c2 = st.columns([1, 2])
    metric = c1.selectbox("CellSqlStat metric", metric_names, index=metric_names.index(default_metric), key="metric_CellSqlStat_special")
    top_sqlids = (
        df[df["metric"] == metric]
        .sort_values("value", ascending=False)["entity"]
        .drop_duplicates()
        .head(8)
        .tolist()
    )
    selected_sqlids = c2.multiselect("SQL IDs", sqlids, default=top_sqlids, key="entity_CellSqlStat_special")

    chart_df = df[df["metric"] == metric].copy()
    if selected_sqlids:
        chart_df = chart_df[chart_df["entity"].isin(selected_sqlids)]
    if chart_df.empty:
        st.info("No CellSqlStat rows match the current selection.")
    else:
        pivot = chart_df.pivot_table(index="timestamp", columns="entity", values="value", aggfunc="max").sort_index()
        st.line_chart(pivot, use_container_width=True)

    detail = pivot_cellsqlstat(df)
    sort_metric = metric if metric in detail.columns else "Memory Bytes"
    if sort_metric in detail.columns:
        detail = detail.sort_values(sort_metric, ascending=False)
    preferred = [
        "timestamp",
        "sqlid",
        "dbname",
        "cdbid",
        "dbid",
        "Duration Seconds",
        "Memory Bytes",
        "%CPU",
        "Requested Bytes",
        "Returned Bytes",
        "IOs",
        "source",
    ]
    visible = [col for col in preferred if col in detail.columns]
    rest = [col for col in detail.columns if col not in visible]
    st.dataframe(detail[visible + rest].head(1000), use_container_width=True, hide_index=True)


def pivot_cellsqlstat(df: pd.DataFrame) -> pd.DataFrame:
    index_cols = ["timestamp", "entity", "source"]
    for col in ("sqlid", "dbname", "cdbid", "dbid"):
        if col in df.columns:
            index_cols.append(col)
    detail = df.pivot_table(index=index_cols, columns="metric", values="value", aggfunc="max").reset_index()
    detail.columns.name = None
    return detail


def render_cellsrvstat(df: pd.DataFrame) -> None:
    with st.expander("CellSrvStat sections", expanded=True):
        st.dataframe(
            pd.DataFrame([{"Section": key, "Description": value} for key, value in CELL_SRVSTAT_DESCRIPTIONS.items()]),
            use_container_width=True,
            hide_index=True,
        )

    sections = sorted(df["section"].dropna().unique().tolist()) if "section" in df.columns else []
    groups = sorted(df["group"].dropna().unique().tolist()) if "group" in df.columns else []
    c1, c2 = st.columns(2)
    section = c1.selectbox("Section", ["All"] + sections, key="section_CellSrvStat")
    group = c2.selectbox("Table / group", ["All"] + groups, key="group_CellSrvStat")

    view = df.copy()
    if section != "All":
        view = view[view["section"] == section]
    if group != "All":
        view = view[view["group"] == group]
    if view.empty:
        st.info("No CellSrvStat rows match this section/group.")
        return

    metric_names = sorted(view["metric"].dropna().unique().tolist())
    default_metric = pick_default_cellsrv_metric(metric_names)
    metric = st.selectbox("Metric", metric_names, index=metric_names.index(default_metric), key="metric_CellSrvStat_special")
    metric_df = view[view["metric"] == metric].copy()
    entity_names = sorted(metric_df["entity"].dropna().unique().tolist())
    top_entities = metric_df.sort_values("value", ascending=False)["entity"].drop_duplicates().head(12).tolist()
    entities = st.multiselect("Entities", entity_names, default=top_entities, key="entity_CellSrvStat_special")
    if entities:
        metric_df = metric_df[metric_df["entity"].isin(entities)]

    if metric_df.empty:
        st.info("No CellSrvStat rows match the current metric/entity selection.")
    else:
        pivot = metric_df.pivot_table(index="timestamp", columns="entity", values="value", aggfunc="max").sort_index()
        st.line_chart(pivot, use_container_width=True)

    preferred = ["timestamp", "section", "group", "entity", "metric", "value", "unit", "sample_value", "source"]
    visible = [col for col in preferred if col in view.columns]
    rest = [col for col in view.columns if col not in visible]
    st.dataframe(view[visible + rest].head(1500), use_container_width=True, hide_index=True)


def pick_default_cellsrv_metric(metric_names: List[str]) -> str:
    preferred = [
        "I/O utilization per disk",
        "Number of disk IO errors",
        "Number of latency threshold warnings during job",
        "High water mark of pending I/O count per disk",
        "OS memory allocated to cellsrv (KB)",
        "Number of threads waiting for network",
        "Total number of jobs waited for buffers",
    ]
    for metric in preferred:
        if metric in metric_names:
            return metric
    return metric_names[0]


def render_cellmem(df: pd.DataFrame) -> None:
    with st.expander("Cellmem column legend", expanded=True):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Metric": metric, "Unit": unit, "Group": group, "Description": description}
                    for metric, unit, group, description in CELL_MEM_FIELDS
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

    groups = sorted(df["group"].dropna().unique().tolist()) if "group" in df.columns else []
    group = st.selectbox("Memory group", ["All"] + groups, key="group_Cellmem")
    view = df.copy()
    if group != "All":
        view = view[view["group"] == group]
    if view.empty:
        st.info("No Cellmem rows match this memory group.")
        return

    metric_names = sorted(view["metric"].dropna().unique().tolist())
    default_metric = pick_default_cellmem_metric(metric_names)
    metric = st.selectbox("Cellmem metric", metric_names, index=metric_names.index(default_metric), key="metric_Cellmem_special")
    chart_df = view[view["metric"] == metric].copy()
    if chart_df.empty:
        st.info("No Cellmem rows match the current metric.")
    else:
        pivot = chart_df.pivot_table(index="timestamp", columns="entity", values="value", aggfunc="max").sort_index()
        st.line_chart(pivot, use_container_width=True)

    detail = pivot_cellmem(df)
    preferred = [
        "timestamp",
        "%OS_AVAIL",
        "OS_AVAIL",
        "OS_TOT",
        "OS_USR",
        "OS_KNL",
        "%CL_AVAIL",
        "CL_AVAIL",
        "CL_MAX",
        "CL_RVD",
        "CL_USD",
        "CL_C",
        "CL_O",
        "CL_K",
        "OTHER_SERVICES",
        "source",
    ]
    visible = [col for col in preferred if col in detail.columns]
    rest = [col for col in detail.columns if col not in visible]
    st.dataframe(detail[visible + rest].head(1500), use_container_width=True, hide_index=True)


def pick_default_cellmem_metric(metric_names: List[str]) -> str:
    preferred = ["%OS_AVAIL", "OS_AVAIL", "%CL_AVAIL", "CL_AVAIL", "CL_USD", "OS_USR", "OS_KNL"]
    for metric in preferred:
        if metric in metric_names:
            return metric
    return metric_names[0]


def pivot_cellmem(df: pd.DataFrame) -> pd.DataFrame:
    detail = df.pivot_table(index=["timestamp", "entity", "source"], columns="metric", values="value", aggfunc="max").reset_index()
    detail.columns.name = None
    return detail


def parse_cellmem(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    fallback_timestamp = timestamp_from_filename(path.name)
    fields = CELL_MEM_FIELDS
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        zzz = ZZZ_RE.search(stripped)
        if zzz:
            fallback_timestamp = parse_any_timestamp(zzz.group(1)) or fallback_timestamp
            continue
        if stripped.startswith("TIMESTAMP"):
            continue
        tokens = stripped.split()
        if not tokens or not re.match(r"^\d{4}-\d{2}-\d{2}T", tokens[0]):
            continue
        timestamp = tokens[0] or fallback_timestamp
        values = [value for token in tokens[1:] if (value := parse_cellmem_number(token)) is not None]
        for idx, value in enumerate(values):
            if len(rows) >= limit:
                break
            if idx < len(fields):
                metric, unit, group, description = fields[idx]
            else:
                metric, unit, group, description = f"extra_{idx + 1}", "", "Extra", "Additional numeric value not mapped in the V1 legend."
            item = row(timestamp, "cellmem", metric, value, unit, path, root)
            item.update({"group": group, "description": description})
            rows.append(item)
    return rows[:limit]


def parse_cellmem_number(token: str) -> Optional[float]:
    cleaned = token.strip().strip("()").replace(",", "")
    if cleaned in {"", "=", "-", "=(", ")"}:
        return None
    if CELLMEM_NUMBER_RE.fullmatch(cleaned) is None:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None


def parse_cellsrvstat(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    section = ""
    group = ""
    table_header: List[str] = []
    for line in lines:
        if len(rows) >= limit:
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("===") and "Current Time" in stripped:
            parsed = parse_cellsrv_current_time(stripped)
            timestamp = parsed or timestamp
            continue
        if stripped.startswith("==") and stripped.endswith("=="):
            section = stripped.strip("= ").strip()
            group = ""
            table_header = []
            continue
        if stripped.startswith("END "):
            group = ""
            table_header = []
            continue
        if stripped.startswith(("#", "zzz")):
            zzz = ZZZ_RE.search(stripped)
            if zzz:
                timestamp = parse_any_timestamp(zzz.group(1)) or timestamp
            continue
        scalar = parse_cellsrv_scalar_row(stripped, timestamp, section, path, root)
        if scalar:
            rows.append(scalar)
            continue
        if group:
            tokens = stripped.split()
            if not any(cellsrv_value_token(token) is not None for token in tokens):
                table_header = tokens
                continue
            rows.extend(parse_cellsrv_table_row(stripped, timestamp, section, group, table_header, path, root))
            continue
        if should_start_cellsrv_group(stripped):
            group = stripped
            table_header = []
    return rows[:limit]


def parse_cellsrv_current_time(line: str) -> str:
    parts = line.split("===", 2)
    text = parts[-1].strip() if parts else ""
    for fmt in ("%a %b %d %H:%M:%S %Y", "%a %b %e %H:%M:%S %Y"):
        try:
            return datetime.strptime(text, fmt).isoformat()
        except Exception:
            pass
    return ""


def should_start_cellsrv_group(line: str) -> bool:
    if not line or line.startswith("Thread "):
        return False
    tokens = line.split()
    return len(tokens) >= 2 and not any(cellsrv_value_token(token) is not None for token in tokens)


def parse_cellsrv_scalar_row(line: str, timestamp: str, section: str, path: Path, root: Path) -> Optional[Dict[str, Any]]:
    tokens = line.split()
    if len(tokens) < 3:
        return None
    sample = cellsrv_value_token(tokens[-2])
    value = cellsrv_value_token(tokens[-1])
    if sample is None or value is None:
        return None
    metric = " ".join(tokens[:-2]).strip()
    if not metric:
        return None
    item = row(timestamp, "CellSrvStat", metric, value, infer_unit(metric, ""), path, root)
    item.update({"section": section, "group": "Scalar counters", "sample_value": sample})
    return item


def parse_cellsrv_table_row(
    line: str,
    timestamp: str,
    section: str,
    group: str,
    table_header: List[str],
    path: Path,
    root: Path,
) -> List[Dict[str, Any]]:
    tokens = line.split()
    rows: List[Dict[str, Any]] = []
    if len(tokens) < 3:
        return rows
    if group == "GridDisk FlashCache stats" and len(tokens) >= 4:
        sample = cellsrv_value_token(tokens[-2])
        value = cellsrv_value_token(tokens[-1])
        if sample is None or value is None:
            return rows
        entity = tokens[0]
        metric = tokens[1]
        item = row(timestamp, entity, metric, value, infer_unit(metric, ""), path, root)
        item.update({"section": section, "group": group, "sample_value": sample})
        rows.append(item)
        return rows
    if table_header and len(tokens) >= 2:
        entity = tokens[0]
        for idx, token in enumerate(tokens[1:], start=1):
            value = cellsrv_value_token(token)
            if value is None:
                continue
            metric = table_header[idx - 1] if idx - 1 < len(table_header) else f"col_{idx}"
            item = row(timestamp, entity, metric, value, infer_unit(metric, ""), path, root)
            item.update({"section": section, "group": group, "sample_value": ""})
            rows.append(item)
        return rows
    sample = cellsrv_value_token(tokens[-2])
    value = cellsrv_value_token(tokens[-1])
    if sample is None or value is None:
        return rows
    entity = " ".join(tokens[:-2]).strip()
    if not entity:
        return rows
    item = row(timestamp, entity, group, value, infer_unit(group, ""), path, root)
    item.update({"section": section, "group": group, "sample_value": sample})
    rows.append(item)
    return rows


def cellsrv_value_token(token: str) -> Optional[float]:
    cleaned = token.strip().replace(",", "")
    if not cleaned or cleaned == "-":
        return None
    if cleaned.endswith("/s"):
        cleaned = cleaned[:-2]
    if re.match(r"^-?\d+(?:\.\d+)?$", cleaned) is None:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None


def parse_cellsqlstat(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    timestamp = timestamp_from_filename(path.name)
    section = ""
    idx = 0
    while idx < len(lines) and len(rows) < limit:
        stripped = lines[idx].strip()
        if stripped.startswith("Current Time:"):
            timestamp = parse_any_timestamp(stripped.split(":", 1)[1].strip()) or timestamp
            idx += 1
            continue
        if stripped.startswith("Top SQL by"):
            section = stripped
            idx += 1
            continue
        tokens = stripped.split()
        if is_cellsqlstat_data_row(tokens):
            parsed = parse_cellsqlstat_tokens(tokens)
            if parsed:
                if idx + 1 < len(lines):
                    continuation = lines[idx + 1].strip().split()
                    if continuation and not is_cellsqlstat_data_row(continuation):
                        cpu = parse_plain_number(continuation[0])
                        if cpu is not None:
                            parsed["%CPU"] = cpu
                        if continuation[-1].endswith("/s"):
                            rate = parse_plain_number(continuation[-1].replace("/s", ""))
                            if rate is not None:
                                parsed["IOs/s"] = rate
                for metric, value in parsed.items():
                    if metric in {"CDBID", "DBID", "SQLID", "DBNAME", "Duration", "section"}:
                        continue
                    if value is None:
                        continue
                    unit = cellsqlstat_unit(metric)
                    item = row(timestamp, str(parsed["SQLID"]), metric, float(value), unit, path, root)
                    item.update(
                        {
                            "sqlid": str(parsed["SQLID"]),
                            "cdbid": str(parsed["CDBID"]),
                            "dbid": str(parsed["DBID"]),
                            "dbname": str(parsed["DBNAME"]),
                            "section": section,
                            "duration": str(parsed.get("Duration", "")),
                        }
                    )
                    rows.append(item)
                    if len(rows) >= limit:
                        break
            idx += 2
            continue
        idx += 1
    return rows


def is_cellsqlstat_data_row(tokens: List[str]) -> bool:
    if len(tokens) < 7:
        return False
    return tokens[0].isdigit() and tokens[1].isdigit() and re.match(r"^[0-9a-zA-Z]{10,}$", tokens[2]) is not None and ":" in tokens[3]


def parse_cellsqlstat_tokens(tokens: List[str]) -> Optional[Dict[str, Any]]:
    if len(tokens) < 8:
        return None
    parsed: Dict[str, Any] = {
        "CDBID": tokens[0],
        "DBID": tokens[1],
        "SQLID": tokens[2],
        "Duration": tokens[3],
        "Duration Seconds": parse_duration_seconds(tokens[3]),
        "Memory Bytes": parse_human_bytes(tokens[4]),
        "DBNAME": tokens[-1],
        "IOs": parse_plain_number(tokens[-2]),
    }
    middle = tokens[5:-2]
    if middle:
        parsed["Requested Bytes"] = parse_human_bytes(middle[0])
    if len(middle) > 1:
        parsed["Returned Bytes"] = parse_human_bytes(middle[1])
    remaining = middle[2:]
    if len(remaining) >= len(CELL_SQLSTAT_BYTE_FIELDS):
        byte_tokens = remaining[-len(CELL_SQLSTAT_BYTE_FIELDS) :]
        percent_tokens = remaining[: -len(CELL_SQLSTAT_BYTE_FIELDS)]
    else:
        byte_tokens = remaining
        percent_tokens = []
    for field, value_text in zip(CELL_SQLSTAT_PERCENT_FIELDS, percent_tokens):
        parsed[field] = parse_plain_number(value_text)
    for field, value_text in zip(CELL_SQLSTAT_BYTE_FIELDS, byte_tokens):
        parsed[field] = parse_human_bytes(value_text)
    return parsed


def parse_duration_seconds(value: str) -> Optional[float]:
    try:
        parts = value.split(":")
        if len(parts) != 3:
            return None
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return None


def parse_human_bytes(value: str) -> Optional[float]:
    number = parse_plain_number(value)
    if number is None:
        return None
    suffix = value.strip().replace(",", "")[-1:].upper()
    multiplier = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
    }.get(suffix, 1)
    return number * multiplier


def parse_plain_number(value: str) -> Optional[float]:
    cleaned = value.strip().replace(",", "")
    if not cleaned or cleaned == "-":
        return None
    if cleaned.endswith("/s"):
        cleaned = cleaned[:-2]
    match = NUMBER_RE.search(cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def cellsqlstat_unit(metric: str) -> str:
    if metric.startswith("%"):
        return "percent"
    if metric.endswith("Bytes"):
        return "bytes"
    if metric == "Duration Seconds":
        return "seconds"
    if metric == "IOs/s":
        return "per_sec"
    if metric == "IOs":
        return "count"
    return ""


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
    if module == "CellSqlStat":
        return detect_cellsqlstat_problems(df)
    if module == "CellSrvStat":
        return detect_cellsrvstat_problems(df)
    if module == "Cellmem":
        return detect_cellmem_problems(df)
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


def detect_cellsrvstat_problems(df: pd.DataFrame) -> List[Dict[str, Any]]:
    checks = [
        ("Number of disk IO errors", 0, "critical", "CellSrv disk I/O errors"),
        ("Number of latency threshold warnings during job", 0, "warning", "CellSrv latency warnings during jobs"),
        ("Number of latency threshold warnings by checker", 0, "warning", "CellSrv checker latency warnings"),
        ("Number of latency threshold warnings for smart IO", 0, "warning", "CellSrv smart I/O latency warnings"),
        ("Number of latency threshold warnings for redolog writes", 0, "critical", "CellSrv redolog write latency warnings"),
        ("I/O utilization per disk", 80, "critical", "High CellSrv per-disk I/O utilization"),
        ("I/O utilization per disk", 60, "warning", "Elevated CellSrv per-disk I/O utilization"),
        ("High water mark of pending I/O count per disk", 100, "warning", "High pending I/O count per disk"),
        ("Total number of jobs waited for buffers", 0, "warning", "CellSrv jobs waited for buffers"),
        ("Current number of jobs waiting for buffers", 0, "critical", "CellSrv jobs currently waiting for buffers"),
        ("Number of threads waiting for network", 100, "warning", "Many CellSrv threads waiting for network"),
        ("Number of threads waiting for resource", 50, "warning", "Many CellSrv threads waiting for resource"),
    ]
    problems: List[Dict[str, Any]] = []
    for metric, threshold, severity, title in checks:
        subset = df[(df["metric"] == metric) & (df["value"] > threshold)]
        if subset.empty:
            continue
        worst = subset.sort_values("value", ascending=False).iloc[0]
        problems.append(
            {
                "severity": severity,
                "tool": "CellSrvStat",
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst["entity"],
                "metric": metric,
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
                "detail": f"{worst.get('section', '')} / {worst.get('group', '')}",
            }
        )
    return problems


def detect_cellmem_problems(df: pd.DataFrame) -> List[Dict[str, Any]]:
    checks = [
        ("%OS_AVAIL", 5, "critical", "Very low OS memory available"),
        ("%OS_AVAIL", 10, "warning", "Low OS memory available"),
        ("%CL_AVAIL", 5, "critical", "Very low cell memory available"),
        ("%CL_AVAIL", 10, "warning", "Low cell memory available"),
        ("OS_AVAIL", 20, "critical", "Very low OS available memory"),
        ("OS_AVAIL", 50, "warning", "Low OS available memory"),
        ("CL_AVAIL", 50, "critical", "Very low cell available memory"),
        ("CL_AVAIL", 100, "warning", "Low cell available memory"),
    ]
    problems: List[Dict[str, Any]] = []
    for metric, threshold, severity, title in checks:
        subset = df[(df["metric"] == metric) & (df["value"] < threshold)]
        if subset.empty:
            continue
        worst = subset.sort_values("value").iloc[0]
        problems.append(
            {
                "severity": severity,
                "tool": "Cellmem",
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst["entity"],
                "metric": metric,
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
                "detail": f"threshold < {threshold} {worst.get('unit', '')}".strip(),
            }
        )
    return problems


def detect_cellsqlstat_problems(df: pd.DataFrame) -> List[Dict[str, Any]]:
    checks = [
        ("Memory Bytes", 8 * 1024**3, "critical", "Very high offload memory by SQL"),
        ("Memory Bytes", 1 * 1024**3, "warning", "High offload memory by SQL"),
        ("%Passthru", 50, "warning", "High passthru percentage"),
        ("%Disk", 80, "warning", "Disk-heavy smart scan"),
        ("Passthru Bytes", 1 * 1024**4, "warning", "Large passthru volume"),
    ]
    problems: List[Dict[str, Any]] = []
    for metric, threshold, severity, title in checks:
        subset = df[(df["metric"] == metric) & (df["value"] > threshold)]
        if subset.empty:
            continue
        worst = subset.sort_values("value", ascending=False).iloc[0]
        problems.append(
            {
                "severity": severity,
                "tool": "CellSqlStat",
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst.get("sqlid", worst["entity"]),
                "metric": metric,
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
                "detail": worst.get("dbname", ""),
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
