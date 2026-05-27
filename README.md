# ExaWatcher Storage Cell Troubleshooting Workbench

Local web workbench for parsing Exadata Storage Cell ExaWatcher bundles, detecting storage-cell health patterns, linking findings to an editable knowledge base, and producing Codex-ready evidence packets.

## Quick Start

Recommended Streamlit workbench:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
scripts/appctl.sh start
scripts/appctl.sh status
scripts/appctl.sh stop
```

Open `http://<server>:8099`, enter the ExaWatcher directory path, and click **Scan / Refresh**.

For a path on the same machine running the app, you can point directly to either an `ExaWatcher_<host>...` directory or an `opt/oracle.ExaWatcher/archive` directory containing `*.ExaWatcher` tool folders.

If the ExaWatcher bundle is on your laptop while the app is running on a remote server, use **Upload local archive** in the sidebar and upload a `.tar.bz2`, `.tar.gz`, `.tgz`, `.tar.xz`, or `.zip` bundle. Uploaded bundles are extracted under `data/uploads/` on the server and ignored by git.

You can also choose **Upload local folder** and select an `archive` folder directly from your browser when your Streamlit version supports directory upload. Python 3.9 environments may only have Streamlit up to 1.50 available, so use **Upload local archive** there. Folder upload mode preserves nested tool directories such as `Iostat.ExaWatcher/` and `Vmstat.ExaWatcher/` while copying them into `data/uploads/` on the server.

The app control script sets Streamlit's upload cap very high by default (`1048576` MB). You can still override it with `EXAWATCHER_MAX_UPLOAD_MB` before running `scripts/appctl.sh restart`.

### Enable folder upload on Linux

Streamlit folder upload requires Streamlit 1.52 or newer, and those Streamlit builds require Python 3.10 or newer. On Oracle Linux/RHEL-like hosts, use Python 3.11 for the app venv:

```bash
cd /root/PP/Exawatcher_ParserTool
scripts/appctl.sh stop

dnf install -y python3.11 python3.11-pip
rm -rf .venv
python3.11 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
python -c "import sys, streamlit; print(sys.version); print(streamlit.__version__)"

scripts/appctl.sh start
```

If `dnf install -y python3.11 python3.11-pip` is not available on that host, stop there and check which Python 3.10+ packages are available before choosing another install method. Python 3.9 remains supported for server paths and archive upload, but not browser folder upload.

Legacy FastAPI backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and import either an extracted ExaWatcher directory or a `.tar.bz2` archive path.

Sample bundle used during development:

```text
/Users/pporacle/Downloads/exacd_logcol_9cce58d4-1ea8-4c4a-8e63-bb44b3fa6044_cmds_gru126171exdcl18_exawatcher_20260513_190000_20260513_220000
```

## Architecture

- `backend/app/parser.py` streams `.dat.xz` files and normalizes supported module metrics.
- `backend/app/patterns.py` detects storage-cell troubleshooting findings.
- `backend/app/store.py` keeps imported case metadata, metrics, snippets, findings, and prompt packets in SQLite plus `data/cases/`.
- `backend/app/main.py` exposes the FastAPI API.
- `frontend/src/` implements the local diagnostic dashboard.
- `kb/storage_cell.yml` is the editable seeded knowledge base.
