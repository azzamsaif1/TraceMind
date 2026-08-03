"""Rusted Recall web application (FastAPI + server-rendered UI, directive section 14)."""
from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Cookie, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rusted_recall import auth, guidance, services, worker
from rusted_recall import evidence as ev
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
    Opportunity,
    Organisation,
    RecallEvent,
    RecallImpact,
    RepairJob,
    RepairQueueItem,
    SourceOfTruthItem,
    SourceOfTruthVersion,
    User,
    Workspace,
)
from rusted_recall.providers.factory import provider_status
from rusted_recall.reporting import to_csv, to_html, to_json, to_pdf
from rusted_recall.storage import get_storage
from rusted_recall.storage.base import ObjectNotFoundError
from rusted_recall.web import judge as judge_vm

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


def _genblaze_versions() -> dict[str, str] | None:
    from rusted_recall.providers.genblaze_official import dist_version, sdk_available

    if not sdk_available():
        return None
    return {
        "core": dist_version("genblaze-core"),
        "connector": dist_version("genblaze-gmicloud"),
    }


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
        queue_depth = worker.queue_depth(s)
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
        observed_category = None
        if last_failed is not None:
            observed_category = last_failed.error_category or None
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
        "provider": provider_status(st, observed_category=observed_category),
        "b2_configured": st.b2_configured,
        "ocr_available": ocr_available(),
        "db_health": db_health,
        "storage_health": storage_health,
        "worker_health": type(runner).__name__,
        "worker_mode": "inline" if st.run_inline_worker else "separate-process",
        "queue_depth": queue_depth,
        "latest_run": run_ctx,
        "latest_object": obj_ctx,
        "provider_verified": provider_verified,
        "last_provider_error": last_provider_error,
        "genblaze_versions": _genblaze_versions(),
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
    """Common context injected into every rendered page (nav auth state + the
    contextual next-step guide derived from real workspace state)."""
    user = _current_user(session, token)
    org = _current_org(session, user)
    guide = None
    try:
        ws = _scoped_workspace(session, user, org)
        guide = guidance.next_step(session, ws, can_edit=_can_edit(ws, org)).as_dict()
    except Exception:  # noqa: BLE001 - guidance must never break a page render
        guide = None
    return {
        "request": request,
        "current_user": user,
        "current_org": org,
        "guide": guide,
    }


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
        # A logged-in company only ever sees its OWN workspace. It must NEVER
        # fall back to the demo or another tenant's workspace (spec 19.5).
        return session.execute(
            select(Workspace).where(Workspace.org_id == org.id).order_by(Workspace.created_at)
        ).scalars().first()
    # Anonymous visitors / judges see the shared demo workspace (org-less).
    return session.execute(
        select(Workspace).where(Workspace.org_id.is_(None)).order_by(Workspace.created_at)
    ).scalars().first()


def _default_workspace(session, user: User | None = None, org: Organisation | None = None) -> Workspace | None:
    return _scoped_workspace(session, user, org)


def _owned_workspace(
    session: Session, user: User | None, org: Organisation | None
) -> Workspace | None:
    """The workspace an authenticated company owns and may edit.

    Returns None for anonymous visitors. Auto-creates the org workspace on
    first use so a freshly signed-up company can immediately onboard its own
    data through the product (no seed script, spec section 19.4)."""
    if user is None or org is None:
        return None
    ws = session.execute(
        select(Workspace).where(Workspace.org_id == org.id).order_by(Workspace.created_at)
    ).scalars().first()
    if ws is None:
        ws = services.create_workspace(session, f"{org.name} Workspace", org_id=org.id)
    return ws


def _can_edit(ws: Workspace | None, org: Organisation | None) -> bool:
    """True when the viewer owns the workspace they are looking at."""
    return bool(ws is not None and org is not None and ws.org_id == org.id)


def _authorize_workspace(ws: Workspace | None, org: Organisation | None) -> None:
    """Enforce tenant isolation (spec section 19.5): org-less workspaces are the
    shared public demo; an org-scoped workspace is only visible to that org."""
    if ws is None:
        raise HTTPException(404, "not found")
    if ws.org_id is not None and (org is None or ws.org_id != org.id):
        raise HTTPException(404, "not found")


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
        org = _current_org(session, user)
        ws = _scoped_workspace(session, user, org)
        assets = []
        sources = []
        if ws:
            rows = session.execute(
                select(Asset).where(Asset.workspace_id == ws.id).order_by(Asset.created_at)
            ).scalars().all()
            for a in rows:
                versions = session.execute(
                    select(AssetVersion).where(AssetVersion.asset_id == a.id).order_by(AssetVersion.version)
                ).scalars().all()
                assets.append({"asset": a, "versions": versions})
            sources = list(session.execute(
                select(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == ws.id)
            ).scalars().all())
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "assets": assets,
            "sources": sources,
            "can_edit": _can_edit(ws, org),
        })
        return templates.TemplateResponse(request, "assets.html", ctx)


@app.get("/sources", response_class=HTMLResponse)
def source_registry(request: Request, rr_session: str | None = Cookie(default=None)) -> HTMLResponse:
    with session_scope() as session:
        user = _current_user(session, rr_session)
        org = _current_org(session, user)
        ws = _scoped_workspace(session, user, org)
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
        ctx.update({"workspace": ws, "items": items, "can_edit": _can_edit(ws, org)})
        return templates.TemplateResponse(request, "sources.html", ctx)


# --- company onboarding: create truth / assets / dependencies (UI-reachable,
# spec sections 12, 19.4) -------------------------------------------------

def _require_owner(session: Session, token: str | None) -> tuple[User, Organisation, Workspace]:
    user = _current_user(session, token)
    org = _current_org(session, user)
    ws = _owned_workspace(session, user, org)
    if user is None or org is None or ws is None:
        raise HTTPException(status_code=303, detail="login required", headers={"Location": "/login"})
    return user, org, ws


@app.post("/sources", response_model=None)
async def create_source(
    request: Request,
    name: str = Form(...),
    type: str = Form("claim"),
    description: str = Form(""),
    label: str = Form(...),
    claim_text: str = Form(...),
    region: str = Form(""),
    reference: UploadFile | None = File(default=None),
    rr_session: str | None = Cookie(default=None),
) -> Response:
    image = await reference.read() if reference is not None and reference.filename else None
    with session_scope() as session:
        user, org, ws = _require_owner(session, rr_session)
        st = get_settings()
        try:
            services.register_source_of_truth(
                session, get_storage(st), ws,
                type=type.strip() or "claim", name=name.strip(),
                description=description.strip(), label=label.strip(),
                claim_text=claim_text.strip(), region=region.strip(),
                reference_image=image or None,
                reference_filename=(reference.filename if reference else "reference.png") or "reference.png",
            )
        except (services.ValidationError, ValueError) as exc:
            raise HTTPException(400, f"invalid source of truth: {exc}") from exc
    return _redirect("/sources")


@app.post("/sources/{item_id}/versions", response_model=None)
async def add_source_version_route(
    request: Request,
    item_id: str,
    label: str = Form(...),
    claim_text: str = Form(...),
    reference: UploadFile | None = File(default=None),
    rr_session: str | None = Cookie(default=None),
) -> Response:
    image = await reference.read() if reference is not None and reference.filename else None
    with session_scope() as session:
        user, org, ws = _require_owner(session, rr_session)
        item = session.get(SourceOfTruthItem, item_id)
        if item is None or item.workspace_id != ws.id:
            raise HTTPException(404, "source of truth not found")
        st = get_settings()
        services.add_source_version(
            session, ws, item, label=label.strip(), claim_text=claim_text.strip(),
            storage=get_storage(st) if image else None,
            reference_image=image or None,
            reference_filename=(reference.filename if reference else "reference.png") or "reference.png",
        )
    return _redirect("/sources")


@app.post("/assets", response_model=None)
async def create_asset(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    asset_type: str = Form("other"),
    campaign: str = Form(""),
    description: str = Form(""),
    publication_status: str = Form("published"),
    declared_source_item_id: str = Form(""),
    parent_asset_id: str = Form(""),
    derivation_method: str = Form(""),
    on_image_text: str = Form(""),
    rr_session: str | None = Cookie(default=None),
) -> Response:
    data = await file.read()
    with session_scope() as session:
        user, org, ws = _require_owner(session, rr_session)
        declared = declared_source_item_id.strip() or None
        parent = parent_asset_id.strip() or None
        if declared is not None:
            it = session.get(SourceOfTruthItem, declared)
            if it is None or it.workspace_id != ws.id:
                raise HTTPException(400, "declared source of truth does not belong to this workspace")
        if parent is not None:
            pa = session.get(Asset, parent)
            if pa is None or pa.workspace_id != ws.id:
                raise HTTPException(400, "parent asset does not belong to this workspace")
        st = get_settings()
        try:
            services.ingest_asset(
                session, get_storage(st), ws,
                data=data, filename=file.filename or "asset.png",
                name=name.strip(), asset_type=asset_type.strip() or "other",
                campaign=campaign.strip(), description=description.strip(),
                publication_status=publication_status.strip() or "published",
                declared_source_item_id=declared,
                parent_asset_id=parent,
                derivation_method=(
                    (derivation_method.strip() or "derived") if parent else None
                ),
                on_image_text=on_image_text.strip(),
            )
        except services.ValidationError as exc:
            raise HTTPException(400, f"invalid asset: {exc}") from exc
    return _redirect("/assets")


@app.post("/dependencies", response_model=None)
def create_dependency(
    request: Request,
    source_node: str = Form(...),
    target_asset_id: str = Form(...),
    note: str = Form(""),
    rr_session: str | None = Cookie(default=None),
) -> Response:
    """Manually declare a dependency edge (spec: define/import dependencies).

    `source_node` is either `sot:<item_id>` or `asset:<asset_id>`; the target is
    always an asset in the owning workspace."""
    with session_scope() as session:
        user, org, ws = _require_owner(session, rr_session)
        target = session.get(Asset, target_asset_id.strip())
        if target is None or target.workspace_id != ws.id:
            raise HTTPException(400, "target asset does not belong to this workspace")
        kind, _, ref = source_node.partition(":")
        src: SourceOfTruthItem | Asset | None
        if kind == "sot":
            src = session.get(SourceOfTruthItem, ref)
        elif kind == "asset":
            src = session.get(Asset, ref)
        else:
            src = None
        if src is None or src.workspace_id != ws.id:
            raise HTTPException(400, "invalid dependency source for this workspace")
        services._add_edge(
            session, ws.id,
            source=source_node.strip(), target=f"asset:{target.id}",
            e=ev.explicit_declaration(note=note.strip() or "declared via product UI"),
        )
        services.audit(session, ws.id, "dependency.declared",
                       {"source": source_node.strip(), "target": f"asset:{target.id}"})
    return _redirect("/assets")


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
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
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
        opportunities = list(session.execute(
            select(Opportunity)
            .where(Opportunity.recall_event_id == recall_id)
            .order_by(Opportunity.created_at)
        ).scalars().all())
        opp_asset_names = {
            a.id: a.name for a in session.execute(
                select(Asset).where(Asset.workspace_id == recall.workspace_id)
            ).scalars().all()
        }
        ctx = _base_ctx(request, session, rr_session)
        ctx.update({
            "workspace": ws,
            "recall": recall,
            "rows": rows,
            "graph": graph,
            "audits": audits,
            "provider": provider_status(st),
            "opportunities": opportunities,
            "opp_asset_names": opp_asset_names,
            "recall_verified": recall.status in ("completed", "partially_completed"),
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
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
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
def run_repairs(recall_id: str, rr_session: str | None = Cookie(default=None)) -> Response:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
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
    rr_session: str | None = Cookie(default=None),
) -> Response:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
        services.record_review_decision(
            session, recall, asset_id=asset_id, decision=decision,
            new_classification=new_classification or None, reason=reason,
        )
    return Response(status_code=303, headers={"Location": f"/recalls/{recall_id}"})


@app.post("/recalls/{recall_id}/opportunities")
def discover_opportunities_route(
    recall_id: str, rr_session: str | None = Cookie(default=None)
) -> Response:
    """Derive Verified Opportunities from a verified recall (spec section 3).
    Idempotent: re-running does not create duplicates."""
    st = get_settings()
    storage = get_storage(st)
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
        assert ws is not None  # _authorize_workspace raises when ws is None
        services.discover_opportunities(session, storage, ws, recall)
    return Response(status_code=303, headers={"Location": f"/recalls/{recall_id}#opportunities"})


@app.post("/opportunities/{opportunity_id}/execute")
def execute_opportunity_route(
    opportunity_id: str, rr_session: str | None = Cookie(default=None)
) -> Response:
    """Execute a Verified Opportunity through the same real engine as repairs.
    Native operations run inline (zero provider calls); generative operations
    route through the pipeline only when a provider is usable."""
    st = get_settings()
    storage = get_storage(st)
    with session_scope() as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            raise HTTPException(404, "opportunity not found")
        ws = session.get(Workspace, opportunity.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
        assert ws is not None  # _authorize_workspace raises when ws is None
        recall_id = opportunity.recall_event_id
        from rusted_recall.providers.factory import build_primary_provider
        from rusted_recall.providers.genblaze import GenblazePipeline

        pipeline = GenblazePipeline(primary=build_primary_provider(st), settings=st)
        if opportunity.status != "verified":
            raise HTTPException(409, "opportunity has no executable plan")
        services.execute_opportunity(
            session, storage, ws, opportunity, pipeline,
            provider_name="gmicloud", model=st.gmicloud_model,
        )
    return Response(status_code=303, headers={"Location": f"/recalls/{recall_id}#opportunities"})


@app.get("/api/recalls/{recall_id}/status")
def recall_status(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
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


# --- Judge Experience (spec Phase 2) -------------------------------------
#
# A thin presentation layer over the SAME services/engine. UI -> thin API
# adapter -> existing Rusted Recall services -> existing DB/worker/provider/
# storage. No domain logic lives here; see rusted_recall.web.judge.


def _judge_recall(
    session: Session, recall_id: str, rr_session: str | None
) -> tuple[RecallEvent, Workspace]:
    """Resolve + authorize a recall for the Judge Experience. Tenant isolation
    is enforced exactly as the rest of the product (org-less demo is public;
    org-scoped recalls only for that org)."""
    recall = session.get(RecallEvent, recall_id)
    if recall is None:
        raise HTTPException(404, "recall not found")
    ws = session.get(Workspace, recall.workspace_id)
    _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
    assert ws is not None  # _authorize_workspace raises when ws is None
    return recall, ws


@app.get("/judge", response_model=None)
def judge_home() -> Response:
    """Judge entry point: seed the production-backed demo if needed and drop the
    visitor into the golden recall's Judge Experience."""
    demo_seed.ensure_seeded(get_settings())
    rid = demo_seed.golden_recall_id(get_settings())
    if not rid:
        raise HTTPException(500, "demo recall unavailable")
    return Response(status_code=303, headers={"Location": f"/judge/recalls/{rid}"})


@app.get("/judge/recalls/{recall_id}", response_class=HTMLResponse, response_model=None)
def judge_recall(
    request: Request, recall_id: str, rr_session: str | None = Cookie(default=None)
) -> HTMLResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        vm = judge_vm.build_view_model(session, recall)
        ctx = {"request": request, "vm": vm}
        return templates.TemplateResponse(request, "judge_recall.html", ctx)


@app.get("/api/judge/recalls/{recall_id}", response_model=None)
def judge_api_recall(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        return JSONResponse(judge_vm.build_view_model(session, recall))


@app.get("/api/judge/recalls/{recall_id}/status", response_model=None)
def judge_api_status(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        jobs = session.execute(
            select(RepairJob).where(RepairJob.recall_event_id == recall_id)
        ).scalars().all()
        # Repair is enqueued as a durable RepairQueueItem and drained
        # asynchronously; the RepairJob rows only appear once the worker claims
        # it. Pending/claimed queue items are therefore in-flight work too, so
        # "active" must reflect them or a poller can see "not active" before the
        # worker has even started.
        pending = session.execute(
            select(func.count())
            .select_from(RepairQueueItem)
            .where(
                RepairQueueItem.recall_event_id == recall_id,
                RepairQueueItem.status.in_(worker.ACTIVE),
            )
        ).scalar_one()
        active = pending > 0 or any(
            j.status in ("queued", "running") for j in jobs
        )
        return JSONResponse({
            "recall_status": recall.status,
            "active": active,
            "assets": judge_vm.build_view_model(session, recall)["assets"],
            "timeline": judge_vm.build_view_model(session, recall)["timeline"],
            "summary": judge_vm.build_view_model(session, recall)["summary"],
        })


@app.get("/api/judge/recalls/{recall_id}/assets/{asset_id}", response_model=None)
def judge_api_asset(
    recall_id: str, asset_id: str, rr_session: str | None = Cookie(default=None)
) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        detail = judge_vm.asset_detail(session, recall, asset_id)
        if detail is None:
            raise HTTPException(404, "asset not in this recall")
        return JSONResponse(detail)


@app.post("/api/judge/recalls/{recall_id}/assets/{asset_id}/review", response_model=None)
def judge_api_review(
    recall_id: str,
    asset_id: str,
    decision: str = Form(...),
    new_classification: str = Form(""),
    reason: str = Form(""),
    rr_session: str | None = Cookie(default=None),
) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        services.record_review_decision(
            session, recall, asset_id=asset_id, decision=decision,
            new_classification=new_classification or None, reason=reason,
        )
        session.flush()
        return JSONResponse(judge_vm.asset_detail(session, recall, asset_id) or {})


@app.post("/api/judge/recalls/{recall_id}/repair", response_model=None)
def judge_api_repair(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        wsid = recall.workspace_id
    get_runner().enqueue(RepairTask(workspace_id=wsid, recall_id=recall_id))
    return JSONResponse({"queued": True})


@app.post("/api/judge/recalls/{recall_id}/replay", response_model=None)
def judge_api_replay(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    """Record a visual replay. Replay never mutates engine state (no repair,
    discovery or execution); it only appends one audit event so Replay Count is
    real and persists across refresh/reopen (directive: Impact Summary)."""
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        services.audit(
            session, recall.workspace_id, "recall.replayed", {"recall_id": recall_id},
            actor="judge", recall_event_id=recall_id,
        )
        session.flush()
        return JSONResponse({"summary": judge_vm.build_view_model(session, recall)["summary"]})


@app.get("/api/judge/recalls/{recall_id}/evidence", response_model=None)
def judge_api_evidence(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        return JSONResponse(judge_vm.evidence_bundle(session, recall))


@app.get("/api/judge/recalls/{recall_id}/opportunities", response_model=None)
def judge_api_opportunities(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    with session_scope() as session:
        recall, _ = _judge_recall(session, recall_id, rr_session)
        return JSONResponse({"opportunities": judge_vm.opportunities_view(session, recall.id)})


@app.post("/api/judge/recalls/{recall_id}/opportunities/discover", response_model=None)
def judge_api_discover(recall_id: str, rr_session: str | None = Cookie(default=None)) -> JSONResponse:
    st = get_settings()
    storage = get_storage(st)
    with session_scope() as session:
        recall, ws = _judge_recall(session, recall_id, rr_session)
        services.discover_opportunities(session, storage, ws, recall)
        session.flush()
        return JSONResponse({
            "opportunities": judge_vm.opportunities_view(session, recall.id),
            "discovery": judge_vm.discovery_summary(session, recall.id),
        })


@app.post("/api/judge/recalls/{recall_id}/opportunities/{opportunity_id}/execute", response_model=None)
def judge_api_execute_opportunity(
    recall_id: str, opportunity_id: str, rr_session: str | None = Cookie(default=None)
) -> JSONResponse:
    st = get_settings()
    storage = get_storage(st)
    with session_scope() as session:
        recall, ws = _judge_recall(session, recall_id, rr_session)
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None or opportunity.recall_event_id != recall_id:
            raise HTTPException(404, "opportunity not found")
        if opportunity.status != "verified":
            raise HTTPException(409, "opportunity has no executable plan")
        from rusted_recall.providers.factory import build_primary_provider
        from rusted_recall.providers.genblaze import GenblazePipeline

        pipeline = GenblazePipeline(primary=build_primary_provider(st), settings=st)
        services.execute_opportunity(
            session, storage, ws, opportunity, pipeline,
            provider_name="gmicloud", model=st.gmicloud_model,
        )
        session.flush()
        return JSONResponse({"opportunities": judge_vm.opportunities_view(session, recall.id)})


# --- reports --------------------------------------------------------------

_REPORT_RENDERERS: dict[str, tuple[Callable[[Any], str | bytes], str]] = {
    "json": (to_json, "application/json"), "csv": (to_csv, "text/csv"),
    "html": (to_html, "text/html"), "pdf": (to_pdf, "application/pdf"),
}


@app.get("/recalls/{recall_id}/report.{fmt}")
def download_report(recall_id: str, fmt: str, rr_session: str | None = Cookie(default=None)) -> Response:
    if fmt not in _REPORT_RENDERERS:
        raise HTTPException(400, "unsupported format")
    with session_scope() as session:
        recall = session.get(RecallEvent, recall_id)
        if recall is None:
            raise HTTPException(404, "recall not found")
        ws = session.get(Workspace, recall.workspace_id)
        _authorize_workspace(ws, _current_org(session, _current_user(session, rr_session)))
        assert ws is not None  # guaranteed by _authorize_workspace
        report = services.build_report(session, ws, recall)
    render, media = _REPORT_RENDERERS[fmt]
    body = render(report)
    data = body if isinstance(body, bytes) else body.encode()
    return Response(
        content=data, media_type=media,
        headers={"Content-Disposition": f'attachment; filename="recall-{recall_id[:8]}.{fmt}"'},
    )
