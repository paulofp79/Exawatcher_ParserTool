from __future__ import annotations

import json
import lzma
import hashlib
import os
import re
import shlex
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


DEFAULT_PATH = "/root/PP/ExaWatcher_gru126171exdcl18.oraclecloud.internal_2026-05-13_19_00_00_3h00m00s"
UPLOAD_ROOT = Path(__file__).resolve().parent / "data" / "uploads"
EXAWATCHER_HOME = Path("/Users/pporacle/opt/oracle.ExaWatcher")
EXAWCHART = EXAWATCHER_HOME / "exawchart.py"
EXAWCHART_COMPAT_DIR = Path(__file__).resolve().parent / "exawatcher_compat"
EXAWCHART_DATE_MASK = "%Y%m%d%H%M.%S"
EXAWCHART_TOOLS = ["Iostat", "CellSrvStat", "Mpstat", "Meminfo", "Cellmem", "Rocestat"]
EXAWCHART_PYTHON_CANDIDATES = [
    "/opt/homebrew/bin/python3.11",
    "/usr/local/bin/python3.11",
    "/usr/bin/python3",
]
HEADER_RE = re.compile(r"#\s*([^:]+):\s*(.*)")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2}\s+[AP]M)")
ZZZ_RE = re.compile(r"zzz\s+<([^>]+)>")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
CELLMEM_NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)")
SIGNAL_WORDS = ("error", "fail", "offline", "drop", "dropped", "retrans", "timeout", "latency", "corrupt")
EXCLUDED_TOOLS = {"Celldiskmd", "ECStat"}
DISKINFO_FIELDS = [
    ("reads_completed", "count"),
    ("reads_merged", "count"),
    ("sectors_read", "sectors"),
    ("time_reading_ms", "ms"),
    ("writes_completed", "count"),
    ("writes_merged", "count"),
    ("sectors_written", "sectors"),
    ("time_writing_ms", "ms"),
    ("ios_in_progress", "count"),
    ("time_doing_io_ms", "ms"),
    ("weighted_time_doing_io_ms", "ms"),
    ("discards_completed", "count"),
    ("discards_merged", "count"),
    ("sectors_discarded", "sectors"),
    ("time_discarding_ms", "ms"),
    ("flushes_completed", "count"),
    ("time_flushing_ms", "ms"),
]
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
    if "active_tool" not in st.session_state:
        st.session_state["active_tool"] = "parser"

    with st.sidebar:
        st.header("Source")
        source_mode = st.radio("Input source", ["Server path", "Upload local archive", "Upload local folder"])
        root_text = ""
        if source_mode == "Server path":
            root_text = st.text_input("ExaWatcher directory", value=DEFAULT_PATH)
            st.caption("Use a path that exists on the machine running this app. Your example `.../opt/oracle.ExaWatcher/archive` path works here when the app runs on that Mac.")
        elif source_mode == "Upload local archive":
            uploaded_file = st.file_uploader(
                "Upload ExaWatcher archive",
                type=["zip", "tar", "gz", "tgz", "bz2", "tbz2", "xz", "txz"],
            )
            upload_disabled = uploaded_file is None
            if st.button("Load uploaded archive", disabled=upload_disabled):
                try:
                    uploaded_root = save_uploaded_archive(uploaded_file)
                    st.session_state["uploaded_root"] = str(uploaded_root)
                    st.cache_data.clear()
                    st.success(f"Loaded uploaded bundle: {uploaded_root}")
                except Exception as exc:
                    st.session_state.pop("uploaded_root", None)
                    st.error(f"Upload import failed: {exc}")
            root_text = st.session_state.get("uploaded_root", "")
            if root_text:
                st.caption(f"Uploaded source: {root_text}")
        else:
            if not supports_directory_upload():
                st.warning(f"Folder upload requires Streamlit 1.52 or newer. This server is running Streamlit {st.__version__}.")
                st.code("pip install -r requirements.txt\nscripts/appctl.sh restart", language="bash")
                st.caption("Until Streamlit is upgraded, use Upload local archive with a `.tar.gz`, `.tar.bz2`, or `.zip` file.")
            else:
                uploaded_files = st.file_uploader(
                    "Choose ExaWatcher folder",
                    accept_multiple_files="directory",
                    help="Select an archive directory containing tool folders like Iostat.ExaWatcher and Vmstat.ExaWatcher.",
                )
                folder_disabled = not uploaded_files
                if st.button("Load uploaded folder", disabled=folder_disabled):
                    try:
                        uploaded_root = save_uploaded_folder(uploaded_files)
                        st.session_state["uploaded_root"] = str(uploaded_root)
                        st.cache_data.clear()
                        st.success(f"Loaded uploaded folder: {uploaded_root}")
                    except Exception as exc:
                        st.session_state.pop("uploaded_root", None)
                        st.error(f"Folder upload failed: {exc}")
                root_text = st.session_state.get("uploaded_root", "")
                if root_text:
                    st.caption(f"Uploaded source: {root_text}")
        max_rows = st.slider("Rows per tool", 5_000, 100_000, 30_000, step=5_000)
        load = st.button("Scan / Refresh", type="primary")
        st.caption("For a remote app, local laptop paths must be sent with archive upload or folder upload.")

    if load:
        st.cache_data.clear()

    if source_mode != "Server path" and not root_text:
        if source_mode == "Upload local archive":
            st.info("Upload a `.tar.bz2`, `.tar.gz`, `.tgz`, or `.zip` ExaWatcher bundle, then click Load uploaded archive.")
        else:
            st.info("Choose your local `archive` folder, then click Load uploaded folder.")
        return

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
    nav1, nav2 = st.columns(2)
    if nav1.button("Parser / Analysis Dashboard", type="primary" if st.session_state["active_tool"] == "parser" else "secondary", use_container_width=True):
        st.session_state["active_tool"] = "parser"
        st.rerun()
    if nav2.button("Oracle Chart Generation", type="primary" if st.session_state["active_tool"] == "chart_generation" else "secondary", use_container_width=True):
        st.session_state["active_tool"] = "chart_generation"
        st.rerun()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tools gathered", len(summaries))
    c2.metric("Files", f"{total_files:,}")
    c3.metric("Size", f"{total_size:,.1f} MB")
    c4.metric("Period", f"{first_time or '?'} to {last_time or '?'}")

    if st.session_state["active_tool"] == "chart_generation":
        render_chart_generation_dashboard(root, summaries, first_time, last_time)
        return

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
    if path.exists() and path.is_dir() and has_exawatcher_dirs(path):
        return path
    if path.exists() and path.is_dir():
        candidates = [candidate for candidate in path.rglob("*") if candidate.is_dir() and has_exawatcher_dirs(candidate)]
        if candidates:
            return sorted(candidates, key=lambda item: (-count_exawatcher_dirs(item), len(item.parts)))[0]
    return path


def supports_directory_upload() -> bool:
    return streamlit_version_tuple() >= (1, 52, 0)


def streamlit_version_tuple() -> tuple[int, int, int]:
    parts = re.findall(r"\d+", getattr(st, "__version__", "0.0.0"))
    values = [int(part) for part in parts[:3]]
    while len(values) < 3:
        values.append(0)
    return tuple(values[:3])


def save_uploaded_archive(uploaded_file: Any) -> Path:
    if uploaded_file is None:
        raise ValueError("No uploaded file was provided.")

    data = uploaded_file.getbuffer()
    digest = hashlib.sha256(data).hexdigest()[:16]
    filename = safe_upload_filename(uploaded_file.name)
    case_name = safe_upload_case_name(filename)
    case_dir = UPLOAD_ROOT / f"{case_name}_{digest}"
    archive_path = case_dir / filename
    extracted_dir = case_dir / "extracted"

    case_dir.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        archive_path.write_bytes(data)

    if not extracted_dir.exists() or not any(extracted_dir.iterdir()):
        extracted_dir.mkdir(parents=True, exist_ok=True)
        extract_uploaded_archive(archive_path, extracted_dir)

    root = find_exawatcher_root(extracted_dir)
    if not root or not root.exists() or not has_exawatcher_dirs(root):
        raise ValueError("The uploaded archive did not contain an ExaWatcher directory with *.ExaWatcher tool folders.")
    return root


def save_uploaded_folder(uploaded_files: List[Any]) -> Path:
    if not uploaded_files:
        raise ValueError("No uploaded files were provided.")

    digest = digest_uploaded_files(uploaded_files)
    folder_name = uploaded_folder_name(uploaded_files)
    case_dir = UPLOAD_ROOT / f"{folder_name}_{digest}"
    files_dir = case_dir / "folder"

    if not files_dir.exists() or not any(files_dir.iterdir()):
        files_dir.mkdir(parents=True, exist_ok=True)
        for uploaded_file in uploaded_files:
            relative_path = uploaded_relative_path(uploaded_file.name)
            target = files_dir / relative_path
            ensure_safe_extract_path(files_dir, str(relative_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(uploaded_file.getbuffer())

    root = find_exawatcher_root(files_dir)
    if not root or not root.exists() or not has_exawatcher_dirs(root):
        raise ValueError("The selected folder did not contain an ExaWatcher archive with *.ExaWatcher tool folders.")
    return root


def digest_uploaded_files(uploaded_files: List[Any]) -> str:
    digest = hashlib.sha256()
    for uploaded_file in uploaded_files:
        digest.update(str(uploaded_file.name).encode("utf-8", errors="replace"))
        digest.update(str(getattr(uploaded_file, "size", "")).encode("utf-8", errors="replace"))
    return digest.hexdigest()[:16]


def uploaded_folder_name(uploaded_files: List[Any]) -> str:
    first_path = str(uploaded_files[0].name).replace("\\", "/")
    first_part = next((part for part in first_path.split("/") if part and part not in {".", ".."}), "uploaded_folder")
    if first_part.endswith(".ExaWatcher"):
        return "archive"
    return safe_upload_case_name(first_part)


def uploaded_relative_path(name: str) -> Path:
    normalized = str(name).replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Unsafe uploaded path: {name}")
    return Path(*parts)


def safe_upload_filename(name: str) -> str:
    filename = Path(name or "exawatcher_upload").name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
    return cleaned or "exawatcher_upload"


def safe_upload_case_name(filename: str) -> str:
    stem = re.sub(r"(?i)\.(tar\.(bz2|gz|xz)|tbz2|tgz|txz|zip|tar)$", "", filename)
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return (cleaned or "exawatcher_upload")[:120]


def extract_uploaded_archive(archive_path: Path, destination: Path) -> None:
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                ensure_safe_extract_path(destination, member.filename)
                archive.extract(member, destination)
        return

    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = []
            for member in archive.getmembers():
                ensure_safe_extract_path(destination, member.name)
                if member.issym() or member.islnk():
                    continue
                members.append(member)
            archive.extractall(destination, members=members)
    except tarfile.TarError as exc:
        raise ValueError("Uploaded file must be a supported archive: .tar, .tar.bz2, .tar.gz, .tgz, .tar.xz, or .zip") from exc


def ensure_safe_extract_path(destination: Path, member_name: str) -> None:
    target = (destination / member_name).resolve()
    base = destination.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Archive member escapes the upload directory: {member_name}") from exc


def has_exawatcher_dirs(path: Path) -> bool:
    return count_exawatcher_dirs(path) > 0


def count_exawatcher_dirs(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir() and child.name.endswith(".ExaWatcher"))


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


def render_chart_generation_dashboard(root: Path, summaries: List[ToolSummary], first_time: str, last_time: str) -> None:
    st.subheader("Oracle ExaWatcher chart generation")
    st.caption("Runs the local Oracle chart generator with the same input tool set used by GetExaWatcherResults.sh.")

    available_tools = [tool for tool in EXAWCHART_TOOLS if (root / f"{tool}.ExaWatcher").exists()]
    missing_tools = [tool for tool in EXAWCHART_TOOLS if tool not in available_tools]
    chart_xz_count = count_chartable_xz_files(root, available_tools)
    host = infer_chart_host(root, summaries)
    default_output = root / f"Charts.ExaWatcher.{host}"

    c1, c2 = st.columns(2)
    start_text = c1.text_input("From time", value=format_exawchart_time(first_time), help=f"Oracle chart mask: {EXAWCHART_DATE_MASK}")
    end_text = c2.text_input("To time", value=format_exawchart_time(last_time), help=f"Oracle chart mask: {EXAWCHART_DATE_MASK}")
    output_text = st.text_input("Output chart directory", value=str(default_output))

    if available_tools:
        st.write(f"Chart inputs: {', '.join(available_tools)} ({chart_xz_count:,} .xz files)")
    if missing_tools:
        st.caption("Not present in this bundle: " + ", ".join(missing_tools))

    if not EXAWCHART.exists():
        st.error(f"Oracle chart script not found: {EXAWCHART}")
        return
    if not available_tools:
        st.warning("No Oracle chartable tool directories were found in the selected ExaWatcher directory.")
        return
    if chart_xz_count == 0:
        st.warning("No .xz files were found in the Oracle chartable tool directories.")
        return

    chart_python = find_exawchart_python()
    if not chart_python:
        st.error("No Python interpreter with both distutils and lxml was found for Oracle exawchart.py.")
        return

    command = build_exawchart_command(root, Path(output_text).expanduser(), available_tools, start_text, end_text, chart_python)
    st.code(shlex.join(command), language="bash")

    if st.button("Generate Oracle Charts", type="primary"):
        with st.spinner("Generating Oracle ExaWatcher charts..."):
            try:
                result = run_exawchart(command)
            except subprocess.TimeoutExpired as exc:
                result = subprocess.CompletedProcess(
                    exc.cmd,
                    124,
                    str(exc.stdout or ""),
                    f"{str(exc.stderr or '')}\nTimed out after {exc.timeout} seconds.",
                )
        st.session_state["last_chart_generation"] = {
            "returncode": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
            "logs": read_recent_chart_logs(Path(output_text).expanduser()),
            "output": output_text,
        }
        st.cache_data.clear()
        html_files = list(Path(output_text).expanduser().rglob("*.html"))
        if result.returncode == 0 and html_files:
            st.success(f"Charts generated in {output_text}")
        elif result.returncode == 0:
            st.warning("The Oracle chart script finished, but no HTML chart files were produced. Check the output log below.")
        else:
            st.error(f"Chart generation failed with exit code {result.returncode}")

    last = st.session_state.get("last_chart_generation")
    if last:
        with st.expander("Last chart generation output", expanded=last["returncode"] != 0):
            st.write(f"Output directory: {last['output']}")
            if last["stdout"]:
                st.code(last["stdout"], language="text")
            if last["stderr"]:
                st.code(last["stderr"], language="text")
            if last.get("logs"):
                st.code(last["logs"], language="text")

    chart_summaries = [summary for summary in scan_tools(str(root)) if summary.tool == "Charts"]
    if chart_summaries:
        st.divider()
        selected_summary = chart_summaries[-1]
        if len(chart_summaries) > 1:
            labels = {summary.path: summary for summary in chart_summaries}
            selected_path = st.selectbox("Generated chart folder", list(labels), index=len(labels) - 1)
            selected_summary = labels[selected_path]
        render_charts_tab(root, selected_summary)


def build_exawchart_command(root: Path, output_dir: Path, tools: List[str], start_text: str, end_text: str, chart_python: str) -> List[str]:
    input_patterns = " ".join(str(root / f"{tool}.ExaWatcher" / "*.xz") for tool in tools)
    command = [
        chart_python,
        str(EXAWCHART),
        "-z",
        input_patterns,
        "-m",
        EXAWCHART_DATE_MASK,
        "-o",
        str(output_dir),
    ]
    if start_text.strip():
        command.extend(["-f", start_text.strip()])
    if end_text.strip():
        command.extend(["-t", end_text.strip()])
    return command


def count_chartable_xz_files(root: Path, tools: List[str]) -> int:
    return sum(1 for tool in tools for _path in (root / f"{tool}.ExaWatcher").glob("*.xz"))


@st.cache_data(show_spinner=False)
def find_exawchart_python() -> str:
    candidates = [*EXAWCHART_PYTHON_CANDIDATES, sys.executable]
    for candidate in candidates:
        if not Path(candidate).exists():
            continue
        result = subprocess.run(
            [candidate, "-c", "import distutils.spawn; import lxml; import exadata_img_pylogger"],
            env=exawchart_env(),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return candidate
    return ""


def run_exawchart(command: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(EXAWATCHER_HOME),
        env=exawchart_env(),
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )


def read_recent_chart_logs(output_dir: Path) -> str:
    if not output_dir.exists():
        return ""
    logs = sorted(output_dir.rglob("exawchart.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not logs:
        return ""
    return logs[0].read_text(encoding="utf-8", errors="replace")[-12000:]


def exawchart_env() -> Dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    paths = [str(EXAWCHART_COMPAT_DIR)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = ":".join(paths)
    return env


def infer_chart_host(root: Path, summaries: List[ToolSummary]) -> str:
    for summary in summaries:
        if summary.files:
            match = re.match(r"\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_[A-Za-z0-9]+ExaWatcher_(.+?)\.dat", Path(summary.files[0]).name)
            if match:
                return safe_path_name(match.group(1))
    match = re.match(r"ExaWatcher_(.+?)_\d{4}_\d{2}_\d{2}", root.name)
    if match:
        return safe_path_name(match.group(1))
    return safe_path_name(root.name) or "local"


def safe_path_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._")[:120]


def format_exawchart_time(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime(EXAWCHART_DATE_MASK)


def render_charts_tab(root: Path, summary: ToolSummary) -> None:
    chart_root = root / summary.path
    html_files = sorted(path for path in chart_root.rglob("*.html") if path.is_file())
    if not html_files:
        st.info("No HTML chart files were found in this Charts directory.")
        return

    choices = [
        path
        for path in html_files
        if not path.name.endswith("_menu.html") and path.name != "index.html"
    ] or html_files
    labels = {chart_label(path): path for path in choices}
    default_label = next((label for label in labels if "IO Summary" in label), next(iter(labels)))
    selected = st.selectbox("ExaWatcher chart", list(labels), index=list(labels).index(default_label), key="chart_file")
    selected_path = labels[selected]

    st.caption(str(selected_path.relative_to(root)))
    html = selected_path.read_text(encoding="utf-8", errors="replace")
    components.html(html, height=900, scrolling=True)

    with st.expander("Chart files", expanded=False):
        rows = [
            {
                "Chart": chart_label(path),
                "File": str(path.relative_to(root)),
                "Size KB": round(path.stat().st_size / 1024, 1),
            }
            for path in html_files
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def chart_label(path: Path) -> str:
    name = path.stem
    if name == "index":
        return "Frameset Index"
    if name.endswith("_menu"):
        return "Menu"
    suffix_map = {
        "cellsrv": "CellSrv",
        "cpu": "CPU",
        "inc": "Incidents",
        "iodetail": "IO Detail",
        "iosummary": "IO Summary",
        "meminfo": "Memory",
        "mp": "MPStat",
        "roce": "RoCE",
    }
    suffix = name.rsplit("_", 1)[-1]
    if suffix in suffix_map:
        return suffix_map[suffix]
    return "Overview"


def render_tool_tab(root: Path, summary: ToolSummary, max_rows: int) -> None:
    st.subheader(summary.tool)
    st.write(f"**Files:** {summary.file_count:,}  **Compressed:** {summary.xz_count:,}  **Period:** {summary.first_time or '?'} to {summary.last_time or '?'}")
    if summary.commands:
        st.code("\n".join(summary.commands), language="bash")

    with st.expander("Files in this tool", expanded=False):
        st.dataframe(pd.DataFrame({"file": summary.files}), use_container_width=True, hide_index=True)

    if summary.tool == "Charts":
        render_charts_tab(root, summary)
        return

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
    if summary.tool == "ECStatJSON":
        render_ecstatjson(df)
        return
    if summary.tool == "Diskinfo":
        render_diskinfo(df)
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
        elif module == "Diskinfo":
            rows.extend(parse_diskinfo(text_rows, file_path, root, max_rows - len(rows)))
        elif module == "ECStatJSON":
            rows.extend(parse_ecstatjson(text_rows, file_path, root, max_rows - len(rows)))
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
    if module == "Diskinfo":
        df = enrich_diskinfo_rates(df)
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


def render_diskinfo(df: pd.DataFrame) -> None:
    with st.expander("Diskinfo /proc/diskstats fields", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [{"Position": idx + 4, "Metric": metric, "Unit": unit} for idx, (metric, unit) in enumerate(DISKINFO_FIELDS)]
            ),
            use_container_width=True,
            hide_index=True,
        )

    families = sorted(df["device_family"].dropna().unique().tolist()) if "device_family" in df.columns else []
    c1, c2 = st.columns([1, 2])
    family = c1.selectbox("Device family", ["All"] + families, key="family_Diskinfo")
    view = df.copy()
    if family != "All":
        view = view[view["device_family"] == family]

    metric_names = sorted(view["metric"].dropna().unique().tolist())
    default_metric = pick_default_diskinfo_metric(metric_names)
    metric = c2.selectbox("Diskinfo metric", metric_names, index=metric_names.index(default_metric), key="metric_Diskinfo_special")
    metric_df = view[view["metric"] == metric].copy()
    device_names = sorted(metric_df["entity"].dropna().unique().tolist())
    top_devices = metric_df.sort_values("value", ascending=False)["entity"].drop_duplicates().head(12).tolist()
    devices = st.multiselect("Devices", device_names, default=top_devices, key="entity_Diskinfo_special")
    if devices:
        metric_df = metric_df[metric_df["entity"].isin(devices)]

    if metric_df.empty:
        st.info("No Diskinfo rows match the current selection.")
    else:
        pivot = metric_df.pivot_table(index="timestamp", columns="entity", values="value", aggfunc="max").sort_index()
        st.line_chart(pivot, use_container_width=True)

    preferred = ["timestamp", "entity", "device_family", "metric", "value", "unit", "derived", "source"]
    visible = [col for col in preferred if col in view.columns]
    rest = [col for col in view.columns if col not in visible]
    st.dataframe(view[visible + rest].head(2000), use_container_width=True, hide_index=True)


def pick_default_diskinfo_metric(metric_names: List[str]) -> str:
    preferred = ["io_util_pct", "read_MBps", "write_MBps", "read_iops", "write_iops", "avg_queue_depth", "read_await_ms", "write_await_ms"]
    for metric in preferred:
        if metric in metric_names:
            return metric
    return metric_names[0]


def render_ecstatjson(df: pd.DataFrame) -> None:
    category_count = df["category"].nunique() if "category" in df.columns else 0
    device_count = df["entity"].nunique()
    stat_count = df["stat"].nunique() if "stat" in df.columns else df["metric"].nunique()
    c1, c2, c3 = st.columns(3)
    c1.metric("Categories", f"{category_count:,}")
    c2.metric("Devices", f"{device_count:,}")
    c3.metric("Stats", f"{stat_count:,}")

    categories = sorted(df["category"].dropna().unique().tolist()) if "category" in df.columns else []
    device_types = sorted(df["device_type"].dropna().unique().tolist()) if "device_type" in df.columns else []
    measures = sorted(df["measure"].dropna().unique().tolist()) if "measure" in df.columns else []

    c1, c2, c3 = st.columns(3)
    category = c1.selectbox("Category", ["All"] + categories, key="category_ECStatJSON")
    device_type = c2.selectbox("Device type", ["All"] + device_types, key="type_ECStatJSON")
    measure = c3.selectbox("Measure", ["All"] + measures, key="measure_ECStatJSON")

    view = df.copy()
    if category != "All":
        view = view[view["category"] == category]
    if device_type != "All":
        view = view[view["device_type"] == device_type]
    if measure != "All":
        view = view[view["measure"] == measure]
    if view.empty:
        st.info("No ECStatJSON rows match these filters.")
        return

    stats = sorted(view["stat"].dropna().unique().tolist()) if "stat" in view.columns else sorted(view["metric"].dropna().unique().tolist())
    if not stats:
        st.info("No ECStatJSON statistics were parsed for this selection.")
        return
    default_stat = pick_default_ecstatjson_stat(view, stats)
    stat = st.selectbox("Statistic", stats, index=stats.index(default_stat), key="stat_ECStatJSON")
    chart_df = view[view["stat"] == stat].copy() if "stat" in view.columns else view[view["metric"] == stat].copy()
    device_names = sorted(chart_df["entity"].dropna().unique().tolist())
    top_devices = chart_df.sort_values("value", ascending=False)["entity"].drop_duplicates().head(12).tolist()
    devices = st.multiselect("Devices", device_names, default=top_devices, key="entity_ECStatJSON_special")
    if devices:
        chart_df = chart_df[chart_df["entity"].isin(devices)]

    if chart_df.empty:
        st.info("No ECStatJSON rows match the selected statistic/devices.")
    else:
        series_name = "entity"
        pivot = chart_df.pivot_table(index="timestamp", columns=series_name, values="value", aggfunc="max").sort_index()
        st.line_chart(pivot, use_container_width=True)

    preferred = ["timestamp", "category", "entity", "device", "device_type", "stat", "measure", "metric", "value", "unit", "source"]
    visible = [col for col in preferred if col in view.columns]
    rest = [col for col in view.columns if col not in visible]
    st.dataframe(view[visible + rest].head(2000), use_container_width=True, hide_index=True)


def pick_default_ecstatjson_stat(df: pd.DataFrame, stats: List[str]) -> str:
    preferred = [
        "latency warning",
        "oltp read hits",
        "oltp write hits",
        "dw read hits",
        "client small read misses",
        "client small write misses",
        "fc metadata writes",
    ]
    lower_to_stat = {stat.lower(): stat for stat in stats}
    for name in preferred:
        if name in lower_to_stat:
            return lower_to_stat[name]
    ranked = df.groupby("stat")["value"].max().sort_values(ascending=False) if "stat" in df.columns else pd.Series(dtype=float)
    if not ranked.empty:
        return str(ranked.index[0])
    return stats[0]


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


def parse_diskinfo(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
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
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 14 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        device = parts[2]
        values = parts[3:]
        item = row(timestamp, device, "major", float(parts[0]), "number", path, root)
        item.update({"device": device, "major": parts[0], "minor": parts[1], "device_family": disk_device_family(device)})
        rows.append(item)
        item = row(timestamp, device, "minor", float(parts[1]), "number", path, root)
        item.update({"device": device, "major": parts[0], "minor": parts[1], "device_family": disk_device_family(device)})
        rows.append(item)
        for idx, (metric, unit) in enumerate(DISKINFO_FIELDS):
            if len(rows) >= limit:
                break
            if idx >= len(values) or not is_number(values[idx]):
                continue
            item = row(timestamp, device, metric, float(values[idx]), unit, path, root)
            item.update({"device": device, "major": parts[0], "minor": parts[1], "device_family": disk_device_family(device)})
            rows.append(item)
        if len(rows) + 2 <= limit and len(values) >= 7:
            sectors_read = parse_plain_number(values[2])
            sectors_written = parse_plain_number(values[6])
            if sectors_read is not None:
                item = row(timestamp, device, "read_MB_total", sectors_read * 512 / 1024 / 1024, "MB", path, root)
                item.update({"device": device, "major": parts[0], "minor": parts[1], "device_family": disk_device_family(device)})
                rows.append(item)
            if sectors_written is not None:
                item = row(timestamp, device, "write_MB_total", sectors_written * 512 / 1024 / 1024, "MB", path, root)
                item.update({"device": device, "major": parts[0], "minor": parts[1], "device_family": disk_device_family(device)})
                rows.append(item)
    return rows[:limit]


def disk_device_family(device: str) -> str:
    if device.startswith("nvme"):
        return "NVMe"
    if device.startswith("md"):
        return "MD RAID"
    if re.match(r"^sd[a-z]+$", device):
        return "SCSI Disk"
    if re.match(r"^.*p\d+$", device):
        return "Partition"
    return "Other"


def enrich_diskinfo_rates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    base = df[df["metric"].isin({"reads_completed", "writes_completed", "sectors_read", "sectors_written", "time_reading_ms", "time_writing_ms", "time_doing_io_ms", "weighted_time_doing_io_ms"})]
    if base.empty:
        return df
    wide = base.pivot_table(
        index=["timestamp", "entity", "source"],
        columns="metric",
        values="value",
        aggfunc="max",
    ).reset_index()
    wide.columns.name = None
    rate_rows: List[Dict[str, Any]] = []
    for entity, group in wide.sort_values("timestamp").groupby("entity"):
        previous: Optional[pd.Series] = None
        for _, current in group.iterrows():
            if previous is None:
                previous = current
                continue
            seconds = (current["timestamp"] - previous["timestamp"]).total_seconds()
            if seconds <= 0:
                previous = current
                continue
            source = current["source"]
            derived = diskinfo_derived_metrics(current, previous, seconds)
            for metric, value, unit in derived:
                if value is None or value < 0:
                    continue
                item = {
                    "timestamp": current["timestamp"],
                    "entity": entity,
                    "metric": metric,
                    "value": float(value),
                    "unit": unit,
                    "source": source,
                    "device": entity,
                    "device_family": disk_device_family(str(entity)),
                    "derived": True,
                }
                rate_rows.append(item)
    if not rate_rows:
        return df
    return pd.concat([df, pd.DataFrame(rate_rows)], ignore_index=True)


def diskinfo_derived_metrics(current: pd.Series, previous: pd.Series, seconds: float) -> List[tuple[str, Optional[float], str]]:
    read_ios = diff_metric(current, previous, "reads_completed")
    write_ios = diff_metric(current, previous, "writes_completed")
    sectors_read = diff_metric(current, previous, "sectors_read")
    sectors_written = diff_metric(current, previous, "sectors_written")
    read_time = diff_metric(current, previous, "time_reading_ms")
    write_time = diff_metric(current, previous, "time_writing_ms")
    busy_time = diff_metric(current, previous, "time_doing_io_ms")
    weighted_time = diff_metric(current, previous, "weighted_time_doing_io_ms")
    return [
        ("read_iops", divide(read_ios, seconds), "iops"),
        ("write_iops", divide(write_ios, seconds), "iops"),
        ("read_MBps", divide(sectors_read * 512 / 1024 / 1024 if sectors_read is not None else None, seconds), "MB/s"),
        ("write_MBps", divide(sectors_written * 512 / 1024 / 1024 if sectors_written is not None else None, seconds), "MB/s"),
        ("read_await_ms", divide(read_time, read_ios), "ms"),
        ("write_await_ms", divide(write_time, write_ios), "ms"),
        ("io_util_pct", divide(busy_time, seconds * 10), "percent"),
        ("avg_queue_depth", divide(weighted_time, seconds * 1000), "count"),
    ]


def diff_metric(current: pd.Series, previous: pd.Series, metric: str) -> Optional[float]:
    if metric not in current or metric not in previous:
        return None
    if pd.isna(current[metric]) or pd.isna(previous[metric]):
        return None
    return float(current[metric]) - float(previous[metric])


def divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


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


def parse_ecstatjson(lines: List[str], path: Path, root: Path, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for timestamp, data in extract_json_objects(lines, timestamp_from_filename(path.name)):
        append_ecstatjson_rows(data, timestamp, rows, path, root, limit)
        if len(rows) >= limit:
            break
    return rows[:limit]


def extract_json_objects(lines: List[str], fallback_timestamp: str) -> List[tuple[str, Any]]:
    objects: List[tuple[str, Any]] = []
    timestamp = fallback_timestamp
    collecting = False
    depth = 0
    buffer: List[str] = []
    object_timestamp = timestamp
    for line in lines:
        stripped = line.strip()
        if not collecting:
            zzz = ZZZ_RE.search(stripped)
            if zzz:
                timestamp = parse_any_timestamp(zzz.group(1)) or timestamp
                continue
            if not stripped.startswith("{"):
                continue
            collecting = True
            buffer = [line]
            object_timestamp = timestamp
            depth = stripped.count("{") - stripped.count("}")
            if depth <= 0:
                collecting = False
        else:
            buffer.append(line)
            depth += stripped.count("{") - stripped.count("}")
            if depth > 0:
                continue
            collecting = False

        if buffer and depth <= 0:
            try:
                objects.append((object_timestamp, json.loads("\n".join(buffer))))
            except Exception:
                pass
            buffer = []
            depth = 0
    return objects


def append_ecstatjson_rows(data: Any, fallback_timestamp: str, rows: List[Dict[str, Any]], path: Path, root: Path, limit: int) -> None:
    if not isinstance(data, dict):
        return
    for category, entries in data.items():
        if len(rows) >= limit:
            return
        if isinstance(entries, list):
            for entry in entries:
                if len(rows) >= limit:
                    return
                if isinstance(entry, dict):
                    append_ecstatjson_entry(str(category), entry, fallback_timestamp, rows, path, root, limit)
        elif isinstance(entries, dict):
            append_ecstatjson_entry(str(category), entries, fallback_timestamp, rows, path, root, limit)


def append_ecstatjson_entry(
    category: str,
    entry: Dict[str, Any],
    fallback_timestamp: str,
    rows: List[Dict[str, Any]],
    path: Path,
    root: Path,
    limit: int,
) -> None:
    name = str(entry.get("name") or entry.get("deviceName") or category)
    device = str(entry.get("deviceName") or "")
    device_type = str(entry.get("intendedDeviceType") or entry.get("xValidationDeviceType") or "")
    timestamp = parse_any_timestamp(str(entry.get("timestampFormatted", ""))) or fallback_timestamp
    stats = entry.get("stats", entry)
    if not isinstance(stats, dict):
        return
    for stat_name, measures in stats.items():
        if len(rows) >= limit:
            return
        if stat_name in {"name", "deviceName", "timestampFormatted", "timestamp", "intendedDeviceType", "xValidationDeviceType", "stats"}:
            continue
        if isinstance(measures, dict):
            for measure, value in measures.items():
                if len(rows) >= limit:
                    return
                if isinstance(value, (int, float)):
                    metric = f"{stat_name} {measure}"
                    item = row(timestamp, name, metric, float(value), ecstatjson_unit(str(measure)), path, root)
                    item.update(
                        {
                            "category": category,
                            "device": device,
                            "device_type": device_type,
                            "stat": str(stat_name),
                            "measure": str(measure),
                        }
                    )
                    rows.append(item)
        elif isinstance(measures, (int, float)):
            item = row(timestamp, name, str(stat_name), float(measures), "", path, root)
            item.update(
                {
                    "category": category,
                    "device": device,
                    "device_type": device_type,
                    "stat": str(stat_name),
                    "measure": "value",
                }
            )
            rows.append(item)


def ecstatjson_unit(measure: str) -> str:
    lower = measure.lower()
    if lower == "bytes":
        return "bytes"
    if lower == "iops":
        return "iops"
    return ""


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
    if module == "ECStatJSON":
        return detect_ecstatjson_problems(df)
    if module == "Diskinfo":
        return detect_diskinfo_problems(df)
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


def detect_diskinfo_problems(df: pd.DataFrame) -> List[Dict[str, Any]]:
    checks = [
        ("io_util_pct", 90, "critical", "High diskstats device utilization"),
        ("io_util_pct", 75, "warning", "Elevated diskstats device utilization"),
        ("read_await_ms", 50, "critical", "High diskstats read await"),
        ("read_await_ms", 20, "warning", "Elevated diskstats read await"),
        ("write_await_ms", 100, "critical", "High diskstats write await"),
        ("write_await_ms", 50, "warning", "Elevated diskstats write await"),
        ("avg_queue_depth", 32, "warning", "Elevated diskstats queue depth"),
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
                "tool": "Diskinfo",
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst["entity"],
                "metric": metric,
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
                "detail": worst.get("device_family", ""),
            }
        )
    return problems


def detect_ecstatjson_problems(df: pd.DataFrame) -> List[Dict[str, Any]]:
    problems: List[Dict[str, Any]] = []
    signal_patterns = [
        ("latency warning", "warning", "ECStatJSON latency warning counters"),
        ("rejected", "warning", "ECStatJSON rejected cacheline counters"),
        ("error", "critical", "ECStatJSON error counters"),
        ("fail", "critical", "ECStatJSON failure counters"),
    ]
    for text, severity, title in signal_patterns:
        subset = df[df["stat"].str.contains(text, case=False, na=False) & (df["value"] > 0)] if "stat" in df.columns else pd.DataFrame()
        if subset.empty:
            continue
        worst = subset.sort_values("value", ascending=False).iloc[0]
        problems.append(
            {
                "severity": severity,
                "tool": "ECStatJSON",
                "title": title,
                "time": str(worst["timestamp"]),
                "entity": worst["entity"],
                "metric": worst["metric"],
                "value": round(float(worst["value"]), 3),
                "source": worst["source"],
                "detail": f"{worst.get('category', '')} / {worst.get('device', '')}".strip(" /"),
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
