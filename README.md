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

You can also choose **Upload local folder** and select an `archive` folder directly from your browser. The folder upload mode preserves nested tool directories such as `Iostat.ExaWatcher/` and `Vmstat.ExaWatcher/` while copying them into `data/uploads/` on the server.

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
