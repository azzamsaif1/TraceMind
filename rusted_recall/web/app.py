"""Rusted Recall web application (FastAPI + server-rendered UI, directive section 14)."""
from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rusted_recall import auth, services
from rusted_recall import usage as usage_metering
from rusted_recall.config import (
    EVIDENCE_WEIGHTS,
    IMPACT_THRESHOLDS,
    get_settings,
    validate_scoring_config,
)
from rusted_recall.db import create_all, session_scope
from rusted_recall.demo import seed as demo_seed
from rusted_recall.jobs import RepairTask, get_runner
from rusted_recall.logging_setup import configure_logging, get_logger, log_context
from rusted_recall.media import ocr_available
from rusted_recall.models import (
    ArtifactObject,
    Asset,
    AssetVersion,
    AuditEvent,
    DependencyEdge,
    GenerationRun,
    Organisation,
    RecallEvent,
    RecallImpact,
    RepairJob,
    SourceOfTruthItem,
    SourceOfTruthVersion,
    User,
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


def _commit_sha() -> str:
    return (
        os.environ.get("RR_COMMIT_SHA")
        or os.environ.get("SOURCE_COMMIT")
        or os.environ.get("RENDER_GIT_COMMIT")
        or "unknown"
    )


@app.get("/diagnostics", response_class=HTMLResponse)
def diagnostics(request: Request) -> HTMLResponse:
    st = get_settings()
    # Live health probes (spec section 22) — read-only, never expose secrets.
    db_health = "ok"
    try:
        with session_scope() as s:
            s.execute(select(func.count()).select_from(Workspace))
    except Exception as exc:  # noqa: BLE001
        db_health = f"error: {exc}"
    storage_health: object
    try:
        storage_health = get_storage(st).health_check()
    except Exception as exc:  # noqa: BLE001
        storage_health = f"unavailable: {exc}"
    runner = get_runner()
    with session_scope() as s:
        latest_run = s.execute(
            select(GenerationRun).order_by(GenerationRun.created_at.desc())
        ).scalars().first()
        latest_object = s.execute(
            select(ArtifactObject).order_by(ArtifactObject.created_at.desc())
        ).scalars().first()
        run_ctx = None
        if latest_run is not None:
            run_ctx = {
                "provider": latest_run.provider,
                "model": latest_run.model,
                "pipeline": latest_run.genblaze_pipeline,
                "attempts": latest_run.attempts,
                "created_at": latest_run.created_at,
            }
        obj_ctx = None
        if latest_object is not None:
            obj_ctx = {
                "kind": latest_object.kind,
                "backend": latest_object.backend,
                "byte_size": latest_object.byte_size,
                "created_at": latest_object.created_at,
                "verified": bool(latest_object.sha256),
            }
        # "Configured" (key present) is distinct from "verified working" (a real
        # generation actually succeeded). Never show green just for a key.
        provider_verified = latest_run is not None and latest_run.provider == "gmicloud"
        last_failed = s.execute(
            select(RepairJob).where(RepairJob.status == "failed").order_by(RepairJob.created_at.desc())
        ).scalars().first()
        last_provider_error = None
        if last_failed is not None:
            last_provider_error = {
                "category": last_failed.error_category or "unknown",
                "detail": (last_failed.error_detail or "")[:200],
                "at": last_failed.created_at,
            }
    ctx = {
        "request": request,
        "settings": st,
        "app_version": app.version,
        "commit_sha": _commit_sha(),
        "provider": provider_status(st),
        "b2_configured": st.b2_configured,
        "ocr_available": ocr_available(),
        "db_health": db_health,
        "storage_health": storage_health,
        "worker_health": type(runner).__name__,
        "latest_run": run_ctx,
        "latest_object": obj_ctx,
        "provider_verified": provider_verified,
        "last_provider_error": last_provider_error,
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

def _current_user(session: Session, token: str | None) -> User | None:
    return auth.user_for_token(session, token)


def _current_org(session: Session, user: User | None) -> Organisation | None:
    if user is None:
        return None
    return auth.primary_org_for_user(session, user)


def _base_ctx(request: Request, session: Session, token: str | None) -> dict:
    """Common context injected into every rendered page (nav auth state)."""
    user = _current_user(session, token)
    org = _current_org(session, user)
    return {"request": request, "current_user": user, "current_org": org}


def _scoped_workspace(
    session: Session, user: User | None, org: Organisation | None
) -> Workspace | None:
    """Return the workspace the viewer should see.

    Authenticated users see their organisation's workspace; anonymous visitors
    (and judges) see the shared demo workspace (the first org-less workspace,
    or simply the first workspace). Real tenant data is never shown to a user
    from a different organisation (spec section 28).
    """
    if org is not None:
        ws = session.execute(
            select(Workspace).where(Workspace.org_id == org.id).order_by(Workspace.created_at)
        ).scalars().first()
        if ws is not None:
            return ws
    demo = session.execute(
        select(Workspace).where(Workspace.org_id.is_(None)).order_by(Workspace.created_at)
    ).scalars().first()
    if demo is not None:
        return demo
    return session.execute(select(Workspace).order_by(Workspace.created_at)).scalars().first()


def _default_workspace(session, user: User | None = None, org: Organisation | None = None) -> Workspace | None:
    return _scoped_workspace(session, user, org)


def _redirect(location: str, *, cookie: tuple[str, str] | None = None, clear: bool = False) -> Response:
    resp = Response(status_code=303, headers={"Location": location})
    if cookie is not None:
        resp.set_cookie(
            cookie[0], cookie[1], httponly=True, samesite="lax",
            secure=get_settings().app_env == "production", max_age=1209600, path="/",
        )
    if clear:
        resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


# --- authentication routes (spec sections 26-27) -------------------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        ctx = _base_ctx(request, session, rr_session)
        ctx["mode"] = "login"
        return templates.TemplateResponse(request, "auth.html", ctx)


@app.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        ctx = _base_ctx(request, session, rr_session)
        ctx["mode"] = "signup"
        return templates.TemplateResponse(request, "auth.html", ctx)


@app.post("/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    org_name: str = Form(""),
) -> Response:
    with session_scope() as session:
        try:
            user, org = auth.sign_up(
                session, email=email, password=password, name=name, org_name=org_name
            )
        except auth.AuthError as exc:
            ctx = _base_ctx(request, session, None)
            ctx.update({"mode": "signup", "error": str(exc), "email": email})
            return templates.TemplateResponse(request, "auth.html", ctx, status_code=400)
        token = auth.create_session(session, user)
    return _redirect("/onboarding", cookie=(auth.SESSION_COOKIE, token))


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    with session_scope() as session:
        try:
            user = auth.authenticate(session, email=email, password=password)
        except auth.AuthError as exc:
            ctx = _base_ctx(request, session, None)
            ctx.update({"mode": "login", "error": str(exc), "email": email})
            return templates.TemplateResponse(request, "auth.html", ctx, status_code=401)
        token = auth.create_session(session, user)
    return _redirect("/app", cookie=(auth.SESSION_COOKIE, token))


@app.get("/logout")
def logout(rr_session: str | None = Cookie(default=None)) -> Response:
    with session_scope() as session:
        auth.destroy_session(session, rr_session)
    return _redirect("/", clear=True)


@app.get("/onboarding", response_class=HTMLResponse, response_model=None)
def onboarding(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse | Response:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        if user is None:
            return _redirect("/login")
        org = _current_org(session, user)
        ws = None
        if org is not None:
            ws = session.execute(
                select(Workspace).where(Workspace.org_id == org.id)
            ).scalars().first()
            if ws is None:
                ws = services.create_workspace(session, f"{org.name} Workspace", org_id=org.id)
        ctx = _base_ctx(request, session, rr_session)
        ctx["workspace"] = ws
        return templates.TemplateResponse(request, "onboarding.html", ctx)


@app.get("/account", response_class=HTMLResponse, response_model=None)
def account(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse | Response:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        if user is None:
            return _redirect("/login")
        org = _current_org(session, user)
        ws = _scoped_workspace(session, user, org)
        summary = usage_metering.usage_summary(session, ws) if ws else {}
        org_summary = usage_metering.org_usage_summary(session, org.id) if org else {}
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "usage": summary,
            "org_usage": org_summary,
            "plan": org.plan if org else "trial",
            "limits": {
                "assets_per_recall": get_settings().demo_max_assets_per_recall,
                "repairs_per_recall": get_settings().demo_max_repairs_per_recall,
            },
        })
        return templates.TemplateResponse(request, "account.html", ctx)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        org = _current_org(session, user)
        ws = _scoped_workspace(session, user, org)
        recalls: list[RecallEvent] = []
        if ws:
            recalls = list(session.execute(
                select(RecallEvent).where(RecallEvent.workspace_id == ws.id).order_by(RecallEvent.created_at.desc())
            ).scalars().all())
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({"workspace": ws, "recalls": recalls})
        return templates.TemplateResponse(request, "history.html", ctx)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    """Product homepage (spec section 5) — not a technical dashboard."""
    with session_scope() as session:
        ctx = _base_ctx(request, session, rr_session)
        return templates.TemplateResponse(request, "landing.html", ctx)


@app.get("/run-live", response_model=None)
def run_live() -> Response:
    """Judge entry (spec section 6): seed the production-backed demo if needed
    and drop the visitor straight into the golden LumaLeaf recall — no account,
    no configuration."""
    demo_seed.ensure_seeded(get_settings())
    rid = demo_seed.golden_recall_id(get_settings())
    if rid is None:
        raise HTTPException(500, "demo seed unavailable")
    return _redirect(f"/recalls/{rid}")


@app.get("/generalisation", response_model=None)
def generalisation() -> Response:
    """Generalisation Test Recall (spec section 11): the Northstar campaign,
    a different topology proving the same engine generalises."""
    demo_seed.ensure_seeded(get_settings())
    rid = demo_seed.generalisation_recall_id(get_settings())
    if rid is None:
        raise HTTPException(500, "generalisation seed unavailable")
    return _redirect(f"/recalls/{rid}")


@app.get("/submission-evidence", response_class=HTMLResponse)
def submission_evidence(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    """Judging-criteria evidence index (spec section 23). Every claim links to
    an inspectable live artefact rather than asking judges to trust the README."""
    st = get_settings()
    with session_scope() as session:
        demo_seed.ensure_seeded(st)
        golden = demo_seed.golden_recall_id(st)
        generalisation_id = demo_seed.generalisation_recall_id(st)
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "golden_recall_id": golden,
            "generalisation_recall_id": generalisation_id,
            "provider": provider_status(st),
            "b2_configured": st.b2_configured,
            "commit_sha": _commit_sha(),
        })
        return templates.TemplateResponse(request, "submission_evidence.html", ctx)


@app.get("/app", response_class=HTMLResponse)
def command_center(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    st = get_settings()
    with session_scope() as session:
        user = _current_user(session, rr_session)
        org = _current_org(session, user)
        ws = _scoped_workspace(session, user, org)
        recalls: list[RecallEvent] = []
        stats = {"assets": 0, "sources": 0, "recalls": 0, "repaired": 0}
        if ws:
            recalls = list(session.execute(
                select(RecallEvent).where(RecallEvent.workspace_id == ws.id).order_by(RecallEvent.created_at.desc())
            ).scalars().all())
            stats["assets"] = session.scalar(select(func.count()).select_from(Asset).where(Asset.workspace_id == ws.id)) or 0
            stats["sources"] = session.scalar(select(func.count()).select_from(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == ws.id)) or 0
            stats["recalls"] = len(recalls)
            stats["repaired"] = session.scalar(
                select(func.count()).select_from(AssetVersion)
                .join(Asset, Asset.id == AssetVersion.asset_id)
                .where(AssetVersion.origin == "repaired", Asset.workspace_id == ws.id)
            ) or 0
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "recalls": recalls,
            "stats": stats,
            "provider": provider_status(st),
            "b2_configured": st.b2_configured,
            "storage_is_b2": st.b2_configured,
        })
        return templates.TemplateResponse(request, "command_center.html", ctx)


@app.get("/assets", response_class=HTMLResponse)
def asset_registry(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        ws = _scoped_workspace(session, user, _current_org(session, user))
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
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({"workspace": ws, "assets": assets})
        return templates.TemplateResponse(request, "assets.html", ctx)


@app.get("/sources", response_class=HTMLResponse)
def source_registry(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        ws = _scoped_workspace(session, user, _current_org(session, user))
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
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({"workspace": ws, "items": items})
        return templates.TemplateResponse(request, "sources.html", ctx)


# --- create recall --------------------------------------------------------

@app.get("/recalls/new", response_class=HTMLResponse)
def new_recall_form(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        ws = _scoped_workspace(session, user, _current_org(session, user))
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
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({"workspace": ws, "items": items})
        return templates.TemplateResponse(request, "create_recall.html", ctx)


@app.post("/recalls")
def create_recall(
    source_item_id: str = Form(...),
    old_version_id: str = Form(...),
    new_version_id: str = Form(...),
    reason: str = Form(...),
    severity: str = Form("high"),
    markets: str = Form(""),
    rr_session: str | None = Cookie(default=None),
) -> Response:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        ws = _scoped_workspace(session, user, _current_org(session, user))
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
def recall_detail(request: Request, recall_id: str, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
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
            if asset is None:
                continue
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
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "recall": recall,
            "rows": rows,
            "graph": graph,
            "audits": audits,
            "provider": provider_status(st),
        })
        return templates.TemplateResponse(request, "recall_detail.html", ctx)


@app.get("/recalls/{recall_id}/evidence", response_class=HTMLResponse)
def recall_evidence(request: Request, recall_id: str, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    """Technical evidence view: ChangeSet, per-asset causal explanations,
    propagation reasons, and the minimal repair plan savings (spec section 24)."""
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        impacts = list(session.execute(
            select(RecallImpact).where(RecallImpact.recall_event_id == recall_id).order_by(RecallImpact.impact_score.desc())
        ).scalars().all())
        rows = []
        for imp in impacts:
            asset = session.get(Asset, imp.asset_id)
            rows.append({"impact": imp, "asset": asset})
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "recall": recall,
            "changeset": recall.changeset or {},
            "plan": recall.repair_plan_graph or {},
            "rows": rows,
            "weights": EVIDENCE_WEIGHTS,
            "thresholds": IMPACT_THRESHOLDS,
        })
        return templates.TemplateResponse(request, "evidence.html", ctx)


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

_REPORT_RENDERERS: dict[str, tuple[Callable[[Any], str | bytes], str]] = {
    "json": (to_json, "application/json"), "csv": (to_csv, "text/csv"),
    "html": (to_html, "text/html"), "pdf": (to_pdf, "application/pdf"),
}


@app.get("/recalls/{recall_id}/report.{fmt}")
def download_report(recall_id: str, fmt: str) -> Response:
    if fmt not in _REPORT_RENDERERS:
        raise HTTPException(400, "unsupported format")
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        report = services.build_report(session, ws, recall)
    render, media = _REPORT_RENDERERS[fmt]
    body = render(report)
    data = body if isinstance(body, bytes) else body.encode()
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="recall-{recall_id[:8]}.{fmt}"'},
    )
