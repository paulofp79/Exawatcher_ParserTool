from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .kb import load_knowledge_base
from .models import CaseMetadata, utc_now
from .parser import parse_bundle
from .patterns import detect_findings
from .store import Store, build_prompt_packet

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
KB_PATH = ROOT / "kb" / "storage_cell.yml"
FRONTEND_DIR = ROOT / "frontend"

app = FastAPI(title="ExaWatcher Storage Cell Troubleshooting Workbench")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
store = Store(DATA_DIR / "exawatcher.db", DATA_DIR / "cases")
app.mount("/src", StaticFiles(directory=FRONTEND_DIR / "src"), name="frontend-src")


class ImportRequest(BaseModel):
    path: str
    name: Optional[str] = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/cases/import")
def import_case(request: ImportRequest) -> dict[str, object]:
    source = Path(request.path).expanduser()
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {source}")
    case_id = case_id_for(str(source.resolve()))
    try:
        result = parse_bundle(str(source), case_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    kb_entries = load_knowledge_base(KB_PATH)
    findings = detect_findings(case_id, result.metrics, result.modules_seen, kb_entries)
    case = CaseMetadata(
        id=case_id,
        name=request.name or source.name,
        source_path=str(source.resolve()),
        imported_at=utc_now(),
        host=result.host,
        started_at=result.started_at,
        ended_at=result.ended_at,
        metric_count=len(result.metrics),
        finding_count=len(findings),
        modules=sorted(result.modules_seen),
    )
    packet = build_prompt_packet(case, findings, result.snippets, kb_entries, result.warnings)
    store.save_case(case, result.metrics, result.snippets, findings, packet)
    return {"case": case, "warnings": result.warnings}


@app.get("/api/cases")
def list_cases() -> list[dict[str, object]]:
    return store.list_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, object]:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.get("/api/cases/{case_id}/timeline")
def get_timeline(case_id: str, limit: int = 5000) -> dict[str, object]:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    metrics = store.get_metrics(case_id, limit)
    return {"metrics": metrics, "limit": limit}


@app.get("/api/cases/{case_id}/findings")
def get_findings(case_id: str) -> dict[str, object]:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    findings = store.get_findings(case_id)
    refs = sorted({ref for finding in findings for ref in finding["evidence_refs"]})
    snippets = store.get_snippets(case_id, refs)
    return {"findings": findings, "snippets": snippets}


@app.get("/api/cases/{case_id}/prompt-packet")
def get_prompt_packet(case_id: str) -> dict[str, object]:
    packet = store.get_prompt_packet(case_id)
    if not packet:
        raise HTTPException(status_code=404, detail="Case not found")
    return packet


def case_id_for(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
