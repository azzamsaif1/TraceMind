"""Rusted Recall web application (FastAPI + server-rendered UI, directive section 14)."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from rusted_recall import services
from rusted_recall.config import (
    EVIDENCE_WEIGHTS,
    IMPACT_THRESHOLDS,
    get_settings,
    validate_scoring_config,
)
from rusted_recall.db import create_all, session_scope
from rusted_recall.jobs import RepairTask, get_runner
from rusted_recall.logging_setup import configure_logging, get_logger, log_context
from rusted_recall.media import ocr_available
from rusted_recall.models import (
    Asset,
    AssetVersion,
    AuditEvent,
    DependencyEdge,
    RecallEvent,
    RecallImpact,
    RepairJob,
    SourceOfTruthItem,
    SourceOfTruthVersion,
    Workspace,
)
from rusted_recall.providers.factory import provider_status
from rusted_recall.reporting import to_csv, to_html, to_json, to_pdf
from rusted_recall.storage import get_storage
from rusted_recall.storage.base import ObjectNotFoundError

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
logger = get_logger(__name__)

app = FastAPI(title="Rusted Recall", version="0.1.0")
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
def _startup() -> None:
    configure_logging()
    validate_scoring_config()
    create_all()


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    with log_context(request_id=request_id, path=request.url.path):
        response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


# --- health / readiness / diagnostics -----------------------------------

@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    checks: dict[str, object] = {}
    ready = True
    try:
        with session_scope() as s:
            s.execute(select(func.count()).select_from(Workspace))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc}"
        ready = False
    st = get_settings()
    storage_health: object
    try:
        storage = get_storage(st)
        storage_health = storage.health_check()
    except Exception as exc:  # noqa: BLE001
        storage_health = f"unavailable: {exc}"
    checks["storage"] = storage_health
    checks["provider"] = provider_status(st)
    return JSONResponse({"ready": ready, "checks": checks}, status_code=200 if ready else 503)


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> HTMLResponse:
    st = get_settings()
    ctx = {
        "request": request,
        "settings": st,
        "provider": provider_status(st),
        "b2_configured": st.b2_configured,
        "ocr_available": ocr_available(),
        "weights": EVIDENCE_WEIGHTS,
        "thresholds": IMPACT_THRESHOLDS,
    }
    return templates.TemplateResponse(request, "diagnostics.html", ctx)


# --- object serving (previews, before/after) -----------------------------

def _guess_type(key: str) -> str:
    if key.endswith(".png"):
        return "image/png"
    if key.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if key.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


@app.get("/obj")
def get_object(key: str) -> Response:
    st = get_settings()
    storage = get_storage(st)
    try:
        data = storage.get_bytes(key)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="object not found") from exc
    return Response(content=data, media_type=_guess_type(key))


# --- command center -------------------------------------------------------

def _default_workspace(session) -> Workspace | None:
    return session.execute(select(Workspace).order_by(Workspace.created_at)).scalars().first()


@app.get("/", response_class=HTMLResponse)
def command_center(request: Request) -> HTMLResponse:
    st = get_settings()
    with session_scope() as session:
        ws = _default_workspace(session)
        recalls = []
        stats = {"assets": 0, "sources": 0, "recalls": 0, "repaired": 0}
        if ws:
            recalls = session.execute(
                select(RecallEvent).where(RecallEvent.workspace_id == ws.id).order_by(RecallEvent.created_at.desc())
            ).scalars().all()
            stats["assets"] = session.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == ws.id)) or 0
            stats["sources"] = session.scalar(select(func.count()).select_from(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == ws.id)) or 0
            stats["recalls"] = len(recalls)
            stats["repaired"] = session.scalar(
                select(func.count()).select_from(AssetVersion).where(AssetVersion.origin == "repaired")
            ) or 0
        ctx = {
            "request": request,
            "workspace": ws,
            "recalls": recalls,
            "stats": stats,
            "provider": provider_status(st),
            "b2_configured": st.b2_configured,
            "storage_is_b2": st.b2_configured,
        }
        return templates.TemplateResponse(request, "command_center.html", ctx)


@app.get("/assets", response_class=HTMLResponse)
def asset_registry(request: Request) -> HTMLResponse:
    with session_scope() as session:
        ws = _default_workspace(session)
        assets = []
        if ws:
            rows = session.execute(
                select(Asset).where(Asset.workspace_id == ws.id).order_by(Asset.created_at)
            ).scalars().all()
            for a in rows:
                versions = session.execute(
                    select(AssetVersion).where(AssetVersion.asset_id == a.id).order_by(AssetVersion.version)
                ).scalars().all()
                assets.append({"asset": a, "versions": versions})
        return templates.TemplateResponse(
            request, "assets.html", {"workspace": ws, "assets": assets}
        )


@app.get("/sources", response_class=HTMLResponse)
def source_registry(request: Request) -> HTMLResponse:
    with session_scope() as session:
        ws = _default_workspace(session)
        items = []
        if ws:
            rows = session.execute(
                select(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == ws.id)
            ).scalars().all()
            for it in rows:
                versions = session.execute(
                    select(SourceOfTruthVersion).where(SourceOfTruthVersion.item_id == it.id).order_by(SourceOfTruthVersion.version)
                ).scalars().all()
                items.append({"item": it, "versions": versions})
        return templates.TemplateResponse(
            request, "sources.html", {"workspace": ws, "items": items}
        )


# --- create recall --------------------------------------------------------

@app.get("/recalls/new", response_class=HTMLResponse)
def new_recall_form(request: Request) -> HTMLResponse:
    with session_scope() as session:
        ws = _default_workspace(session)
        items = []
        if ws:
            rows = session.execute(
                select(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == ws.id)
            ).scalars().all()
            for it in rows:
                versions = session.execute(
                    select(SourceOfTruthVersion).where(SourceOfTruthVersion.item_id == it.id).order_by(SourceOfTruthVersion.version)
                ).scalars().all()
                items.append({"item": it, "versions": versions})
        return templates.TemplateResponse(
            request, "create_recall.html", {"workspace": ws, "items": items}
        )


@app.post("/recalls")
def create_recall(
    source_item_id: str = Form(...),
    old_version_id: str = Form(...),
    new_version_id: str = Form(...),
    reason: str = Form(...),
    severity: str = Form("high"),
    markets: str = Form(""),
) -> Response:
    with session_scope() as session:
        ws = _default_workspace(session)
        if ws is None:
            raise HTTPException(400, "no workspace")
        item = session.get(SourceOfTruthItem, source_item_id)
        old_v = session.get(SourceOfTruthVersion, old_version_id)
        new_v = session.get(SourceOfTruthVersion, new_version_id)
        if not (item and old_v and new_v):
            raise HTTPException(400, "invalid source/version selection")
        recall = services.create_recall_event(
            session, ws, item=item, old_version=old_v, new_version=new_v,
            reason=reason, severity=severity,
            markets=[m.strip() for m in markets.split(",") if m.strip()],
        )
        services.run_impact_analysis(session, ws, recall)
        rid = recall.id
    return Response(status_code=303, headers={"Location": f"/recalls/{rid}"})


# --- recall detail (impact map / review / repair / gallery / audit) -------

@app.get("/recalls/{recall_id}", response_class=HTMLResponse)
def recall_detail(request: Request, recall_id: str) -> HTMLResponse:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        impacts = session.execute(
            select(RecallImpact).where(RecallImpact.recall_event_id == recall_id).order_by(RecallImpact.impact_score.desc())
        ).scalars().all()
        rows = []
        for imp in impacts:
            asset = session.get(Asset, imp.asset_id)
            uploaded = session.execute(
                select(AssetVersion).where(AssetVersion.asset_id == asset.id, AssetVersion.origin == "uploaded").order_by(AssetVersion.version)
            ).scalars().first()
            repaired = session.execute(
                select(AssetVersion).where(AssetVersion.asset_id == asset.id, AssetVersion.origin == "repaired").order_by(AssetVersion.version.desc())
            ).scalars().first()
            job = session.execute(
                select(RepairJob).where(RepairJob.recall_event_id == recall_id, RepairJob.asset_id == asset.id).order_by(RepairJob.created_at.desc())
            ).scalars().first()
            rows.append({"impact": imp, "asset": asset, "uploaded": uploaded, "repaired": repaired, "job": job})

        edges = session.execute(
            select(DependencyEdge).where(DependencyEdge.workspace_id == recall.workspace_id)
        ).scalars().all()
        graph = _graph_payload(session, recall, edges)
        audits = session.execute(
            select(AuditEvent).where(AuditEvent.recall_event_id == recall_id).order_by(AuditEvent.created_at)
        ).scalars().all()
        st = get_settings()
        ctx = {
            "request": request,
            "workspace": ws,
            "recall": recall,
            "rows": rows,
            "graph": graph,
            "audits": audits,
            "provider": provider_status(st),
        }
        return templates.TemplateResponse(request, "recall_detail.html", ctx)


def _graph_payload(session, recall: RecallEvent, edges) -> dict:
    item = session.get(SourceOfTruthItem, recall.source_item_id)
    nodes: dict[str, dict] = {}
    src_id = f"sot:{recall.source_item_id}"
    nodes[src_id] = {"id": src_id, "label": item.name if item else "source", "kind": "source"}
    links = []
    for e in edges:
        for nid in (e.source_node, e.target_node):
            if nid not in nodes:
                label = nid.split(":", 1)[-1][:8]
                kind = "source" if nid.startswith("sot:") else "asset"
                if nid.startswith("asset:"):
                    a = session.get(Asset, nid.split(":", 1)[1])
                    if a:
                        label = a.name
                nodes[nid] = {"id": nid, "label": label, "kind": kind}
        links.append({
            "source": e.source_node, "target": e.target_node,
            "type": e.edge_type, "confidence": round(e.confidence, 2),
        })
    return {"nodes": list(nodes.values()), "links": links}


@app.post("/recalls/{recall_id}/repair")
def run_repairs(recall_id: str) -> Response:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        wsid = recall.workspace_id
    get_runner().enqueue(RepairTask(workspace_id=wsid, recall_id=recall_id))
    return Response(status_code=303, headers={"Location": f"/recalls/{recall_id}"})


@app.post("/recalls/{recall_id}/review")
def review(
    recall_id: str,
    asset_id: str = Form(...),
    decision: str = Form(...),
    new_classification: str = Form(""),
    reason: str = Form(""),
) -> Response:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        services.record_review_decision(
            session, recall, asset_id=asset_id, decision=decision,
            new_classification=new_classification or None, reason=reason,
        )
    return Response(status_code=303, headers={"Location": f"/recalls/{recall_id}"})


@app.get("/api/recalls/{recall_id}/status")
def recall_status(recall_id: str) -> JSONResponse:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        jobs = session.execute(
            select(RepairJob).where(RepairJob.recall_event_id == recall_id)
        ).scalars().all()
        return JSONResponse({
            "recall_status": recall.status,
            "jobs": [
                {
                    "asset_id": j.asset_id, "status": j.status, "stage": j.stage,
                    "attempts": j.attempts, "error_category": j.error_category,
                    "result_version_id": j.result_version_id,
                }
                for j in jobs
            ],
        })


# --- reports --------------------------------------------------------------

_REPORT_RENDERERS = {"json": (to_json, "application/json"), "csv": (to_csv, "text/csv"),
                     "html": (to_html, "text/html"), "pdf": (to_pdf, "application/pdf")}


@app.get("/recalls/{recall_id}/report.{fmt}")
def download_report(recall_id: str, fmt: str) -> Response:
    if fmt not in _REPORT_RENDERERS:
        raise HTTPException(400, "unsupported format")
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        report = services.build_report(session, ws, recall)
    render, media = _REPORT_RENDERERS[fmt]
    body = render(report)
    data = body if isinstance(body, bytes) else body.encode()
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="recall-{recall_id[:8]}.{fmt}"'},
    )
