"""Production services: ingestion, dependency analysis, impact, review, repair,
reporting. Both the web UI and the demo seed command call these same code paths
(directive sections 6, 15) — the seed never inserts graph rows directly.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from rusted_recall import evidence as ev
from rusted_recall import recall as recall_fsm
from rusted_recall import usage as usage_metering
from rusted_recall.changeset import ChangeSet, propose_changeset
from rusted_recall.evidence import ALGO_VERSION, Evidence
from rusted_recall.graph import DependencyGraph
from rusted_recall.hashing import perceptual_hash_bytes, sha256_bytes
from rusted_recall.logging_setup import get_logger, log_context
from rusted_recall.manifests import build_repair_manifest, new_id
from rusted_recall.media import (
    ALLOWED_MIME,
    MAX_UPLOAD_BYTES,
    content_type_for,
    extract_text,
    image_dimensions,
    make_preview,
)
from rusted_recall.models import (
    AnalysisRun,
    ArtifactObject,
    Asset,
    AssetVersion,
    AuditEvent,
    DependencyEdge,
    GenerationRun,
    RecallEvent,
    RecallImpact,
    RepairJob,
    RepairPlanRow,
    ReviewDecision,
    SourceOfTruthItem,
    SourceOfTruthVersion,
    ValidationResultRow,
    Workspace,
)
from rusted_recall.planner import MinimalRepairPlanner, PlannerAsset
from rusted_recall.propagation import (
    AssetInput,
    ChangePropagationEngine,
    EdgeInput,
)
from rusted_recall.providers.base import GenerationRequest, ProviderConfigError
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.repair import (
    DEFAULT_RETRY_POLICY,
    RepairPlan,
    build_repair_instruction,
)
from rusted_recall.storage.base import ObjectKeys, StorageBackend
from rusted_recall.validation import validate_repaired_image

logger = get_logger(__name__)


class ValidationError(ValueError):
    pass


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def audit(session: Session, workspace_id: str, event: str, detail: dict, *, actor: str = "system", recall_event_id: str | None = None) -> None:
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            recall_event_id=recall_event_id,
            actor=actor,
            event=event,
            detail=detail,
        )
    )


def _track_object(session: Session, workspace_id: str, stored, kind: str) -> None:
    session.add(
        ArtifactObject(
            workspace_id=workspace_id,
            b2_key=stored.key,
            kind=kind,
            sha256=stored.sha256,
            content_type=stored.content_type,
            byte_size=stored.size,
            backend=getattr(stored, "backend", "unknown"),
        )
    )


# --- workspace -----------------------------------------------------------

def create_workspace(
    session: Session, name: str, *, org_id: str | None = None
) -> Workspace:
    ws = Workspace(name=name, slug=_unique_workspace_slug(session, _slugify(name)), org_id=org_id)
    session.add(ws)
    session.flush()
    audit(session, ws.id, "workspace.created", {"name": name, "org_id": org_id})
    return ws


def _unique_workspace_slug(session: Session, base: str) -> str:
    base = base or "workspace"
    slug = base
    n = 1
    while session.execute(
        select(Workspace).where(Workspace.slug == slug)
    ).scalar_one_or_none() is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def get_workspace_by_slug(session: Session, slug: str) -> Workspace | None:
    return session.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()


# --- source of truth -----------------------------------------------------

def register_source_of_truth(
    session: Session,
    storage: StorageBackend,
    workspace: Workspace,
    *,
    type: str,
    name: str,
    description: str,
    label: str,
    claim_text: str,
    reference_image: bytes | None = None,
    reference_filename: str = "reference.png",
    region: str = "",
    tags: list[str] | None = None,
) -> tuple[SourceOfTruthItem, SourceOfTruthVersion]:
    item = SourceOfTruthItem(
        workspace_id=workspace.id,
        type=type,
        name=name,
        description=description,
        region=region,
        tags=tags or [],
    )
    session.add(item)
    session.flush()

    version = SourceOfTruthVersion(
        item_id=item.id,
        version=1,
        label=label,
        claim_text=claim_text,
        valid_from=datetime.now(timezone.utc),
    )
    session.add(version)
    session.flush()

    keys = ObjectKeys(workspace.id)
    if reference_image is not None:
        version.reference_sha256 = sha256_bytes(reference_image)
        try:
            version.reference_phash = perceptual_hash_bytes(reference_image)
        except Exception:  # noqa: BLE001
            version.reference_phash = None
        key = keys.sot_original(item.id, version.id, reference_filename)
        stored = storage.put_bytes(key, reference_image, content_type_for(reference_image))
        version.b2_key = key
        _track_object(session, workspace.id, stored, "sot_original")

    audit(session, workspace.id, "sot.registered", {"item_id": item.id, "type": type, "label": label})
    return item, version


def add_source_version(
    session: Session,
    workspace: Workspace,
    item: SourceOfTruthItem,
    *,
    label: str,
    claim_text: str,
    storage: StorageBackend | None = None,
    reference_image: bytes | None = None,
    reference_filename: str = "reference.png",
) -> SourceOfTruthVersion:
    latest = max((v.version for v in item.versions), default=0)
    version = SourceOfTruthVersion(
        item_id=item.id,
        version=latest + 1,
        label=label,
        claim_text=claim_text,
        valid_from=datetime.now(timezone.utc),
    )
    session.add(version)
    session.flush()
    if reference_image is not None and storage is not None:
        version.reference_sha256 = sha256_bytes(reference_image)
        try:
            version.reference_phash = perceptual_hash_bytes(reference_image)
        except Exception:  # noqa: BLE001
            version.reference_phash = None
        keys = ObjectKeys(workspace.id)
        key = keys.sot_original(item.id, version.id, reference_filename)
        stored = storage.put_bytes(key, reference_image, content_type_for(reference_image))
        version.b2_key = key
        _track_object(session, workspace.id, stored, "sot_original")
    audit(session, workspace.id, "sot.version_added", {"item_id": item.id, "version": version.version, "label": label})
    return version


# --- ingestion + analysis ------------------------------------------------

def ingest_asset(
    session: Session,
    storage: StorageBackend,
    workspace: Workspace,
    *,
    data: bytes,
    filename: str,
    name: str,
    asset_type: str,
    campaign: str = "",
    description: str = "",
    publication_status: str = "draft",
    declared_source_item_id: str | None = None,
    parent_asset_id: str | None = None,
    derivation_method: str | None = None,
    on_image_text: str = "",
) -> tuple[Asset, AssetVersion]:
    """Real ingestion pipeline (directive section 3, step 3)."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError(f"file too large: {len(data)} bytes > {MAX_UPLOAD_BYTES}")
    mime = content_type_for(data)
    if mime not in ALLOWED_MIME:
        raise ValidationError(f"unsupported media type: {mime}")

    sha = sha256_bytes(data)
    phash = perceptual_hash_bytes(data)
    width, height = image_dimensions(data)
    ocr_text = extract_text(data)
    extracted = ocr_text if ocr_text is not None else on_image_text

    asset = Asset(
        workspace_id=workspace.id,
        name=name,
        asset_type=asset_type,
        campaign=campaign,
        description=description,
        publication_status=publication_status,
        parent_asset_id=parent_asset_id,
        derivation_method=derivation_method,
    )
    session.add(asset)
    session.flush()

    keys = ObjectKeys(workspace.id)
    version_id = new_id()
    original_key = keys.asset_original(asset.id, version_id, filename)
    version = AssetVersion(
        id=version_id,
        asset_id=asset.id,
        version=1,
        origin="uploaded",
        sha256=sha,
        phash=phash,
        width=width,
        height=height,
        content_type=mime,
        byte_size=len(data),
        extracted_text=extracted,
        b2_key=original_key,
    )
    session.add(version)
    session.flush()

    stored = storage.put_bytes(original_key, data, mime, metadata={"sha256": sha, "phash": phash})
    _track_object(session, workspace.id, stored, "asset_original")

    preview = make_preview(data)
    preview_key = keys.asset_preview(asset.id, version.id, "preview.png")
    pstored = storage.put_bytes(preview_key, preview, "image/png")
    version.preview_b2_key = preview_key
    _track_object(session, workspace.id, pstored, "asset_preview")

    # analysis.json
    analysis = {
        "sha256": sha,
        "phash": phash,
        "dimensions": [width, height],
        "ocr_available": ocr_text is not None,
        "extracted_text": extracted,
    }
    analysis_key = keys.asset_analysis(asset.id, version.id)
    astored = storage.put_bytes(
        analysis_key, json.dumps(analysis, indent=2).encode(), "application/json"
    )
    version.analysis_b2_key = analysis_key
    _track_object(session, workspace.id, astored, "asset_analysis")

    # parent-child derivation edge
    if parent_asset_id:
        _add_edge(
            session,
            workspace.id,
            source=f"asset:{parent_asset_id}",
            target=f"asset:{asset.id}",
            e=ev.parent_child(parent_asset_id, asset.id),
        )

    # explicit declaration edge to a source-of-truth item
    if declared_source_item_id:
        _add_edge(
            session,
            workspace.id,
            source=f"sot:{declared_source_item_id}",
            target=f"asset:{asset.id}",
            e=ev.explicit_declaration(note="declared at ingestion"),
        )

    # inferred evidence vs every source-of-truth item's latest version
    _analyze_asset_against_sources(session, workspace, asset, version)

    usage_metering.record_usage(session, workspace, usage_metering.EVENT_ASSET_UPLOADED)
    usage_metering.record_usage(
        session, workspace, usage_metering.EVENT_STORAGE_BYTES_ADDED, quantity=float(len(data))
    )
    usage_metering.record_usage(session, workspace, usage_metering.EVENT_ANALYSIS_COMPLETED)
    audit(session, workspace.id, "asset.ingested", {"asset_id": asset.id, "sha256": sha, "b2_key": original_key})
    return asset, version


def _add_edge(session: Session, workspace_id: str, *, source: str, target: str, e: Evidence) -> None:
    session.add(
        DependencyEdge(
            workspace_id=workspace_id,
            source_node=source,
            target_node=target,
            edge_type=e.edge_type,
            confidence=e.confidence,
            evidence_type=e.evidence_type,
            evidence_details=e.details,
            algorithm_version=e.algorithm_version,
            human_confirmed=e.human_confirmed,
        )
    )


def _analyze_asset_against_sources(
    session: Session, workspace: Workspace, asset: Asset, version: AssetVersion
) -> None:
    items = session.execute(
        select(SourceOfTruthItem).where(SourceOfTruthItem.workspace_id == workspace.id)
    ).scalars().all()
    for item in items:
        latest = max(item.versions, key=lambda v: v.version, default=None)
        if latest is None:
            continue
        source_node = f"sot:{item.id}"
        target = f"asset:{asset.id}"

        if latest.reference_sha256:
            dup = ev.sha256_duplicate(version.sha256, latest.reference_sha256)
            if dup:
                _add_edge(session, workspace.id, source=source_node, target=target, e=dup)
        if latest.reference_phash and version.phash:
            der = ev.phash_derivative(version.phash, latest.reference_phash)
            if der:
                _add_edge(session, workspace.id, source=source_node, target=target, e=der)
            vis = ev.visual_similarity(version.phash, latest.reference_phash)
            if vis:
                _add_edge(session, workspace.id, source=source_node, target=target, e=vis)
        if latest.claim_text and version.extracted_text:
            ocr = ev.ocr_text_match(version.extracted_text, latest.claim_text)
            if ocr:
                _add_edge(session, workspace.id, source=source_node, target=target, e=ocr)
        if item.description and asset.description:
            sem = ev.semantic_similarity(asset.description, item.description)
            if sem:
                _add_edge(session, workspace.id, source=source_node, target=target, e=sem)


# --- recall + impact -----------------------------------------------------

def create_recall_event(
    session: Session,
    workspace: Workspace,
    *,
    item: SourceOfTruthItem,
    old_version: SourceOfTruthVersion,
    new_version: SourceOfTruthVersion,
    reason: str,
    severity: str = "high",
    markets: list[str] | None = None,
    created_by: str = "demo-user",
    changeset: ChangeSet | None = None,
) -> RecallEvent:
    # Automatic change understanding (spec section 11): if the caller did not
    # supply a structured ChangeSet, propose one by diffing the two versions.
    if changeset is None:
        changeset = propose_changeset(
            entity_type=item.type,
            old_version_id=old_version.id,
            new_version_id=new_version.id,
            old_label=old_version.label,
            new_label=new_version.label,
            old_claim=old_version.claim_text,
            new_claim=new_version.claim_text,
            old_phash=old_version.reference_phash,
            new_phash=new_version.reference_phash,
        )
    recall = RecallEvent(
        workspace_id=workspace.id,
        source_item_id=item.id,
        old_version_id=old_version.id,
        new_version_id=new_version.id,
        reason=reason,
        severity=severity,
        markets=markets or [],
        created_by=created_by,
        status=recall_fsm.DRAFT,
        changeset=changeset.as_dict(),
    )
    session.add(recall)
    session.flush()
    usage_metering.record_usage(session, workspace, usage_metering.EVENT_RECALL_CREATED)
    audit(
        session,
        workspace.id,
        "recall.created",
        {"recall_id": recall.id, "reason": reason, "changeset": changeset.summary()},
        recall_event_id=recall.id,
    )
    return recall


def _set_status(session: Session, recall: RecallEvent, target: str) -> None:
    recall.status = recall_fsm.transition(recall.status, target)
    audit(session, recall.workspace_id, "recall.status", {"status": target}, recall_event_id=recall.id)


def _build_graph(session: Session, workspace_id: str) -> DependencyGraph:
    g = DependencyGraph()
    edges = session.execute(
        select(DependencyEdge).where(DependencyEdge.workspace_id == workspace_id)
    ).scalars().all()
    for e in edges:
        g.add_edge(e.source_node, e.target_node, e.edge_type, e.confidence)
    return g


def _edges_for_target(session: Session, workspace_id: str, source_item_id: str, asset_id: str) -> list[DependencyEdge]:
    return list(
        session.execute(
            select(DependencyEdge).where(
                DependencyEdge.workspace_id == workspace_id,
                DependencyEdge.target_node == f"asset:{asset_id}",
            )
        ).scalars().all()
    )


def run_impact_analysis(session: Session, workspace: Workspace, recall: RecallEvent) -> AnalysisRun:
    """Compute the affected set via the Change Propagation Engine, then the
    Minimal Repair Plan (spec sections 15-18)."""
    with log_context(workspace_id=workspace.id, recall_id=recall.id):
        if recall.status == recall_fsm.DRAFT:
            _set_status(session, recall, recall_fsm.ANALYSING)

        graph = _build_graph(session, workspace.id)
        source_node = f"sot:{recall.source_item_id}"

        config_hash = hashlib.sha256(
            json.dumps({"algo": ALGO_VERSION}, sort_keys=True).encode()
        ).hexdigest()
        run = AnalysisRun(
            workspace_id=workspace.id,
            recall_event_id=recall.id,
            model_version=ALGO_VERSION,
            config_hash=config_hash,
        )
        session.add(run)

        # clear prior impacts for idempotent re-analysis
        for old in list(recall.impacts):
            session.delete(old)
        session.flush()

        assets = list(
            session.execute(
                select(Asset).where(Asset.workspace_id == workspace.id)
            ).scalars().all()
        )
        changeset = ChangeSet.from_dict(recall.changeset or {})

        edges_by_target: dict[str, list[EdgeInput]] = {}
        node_labels: dict[str, str] = {}
        item = session.get(SourceOfTruthItem, recall.source_item_id)
        node_labels[source_node] = item.name if item else "source"
        engine_assets: list[AssetInput] = []
        markets = set(recall.markets or [])
        for asset in assets:
            node = f"asset:{asset.id}"
            node_labels[node] = asset.name
            rows = _edges_for_target(session, workspace.id, recall.source_item_id, asset.id)
            edges_by_target[node] = [
                EdgeInput(
                    edge_type=r.edge_type,
                    confidence=r.confidence,
                    human_confirmed=r.human_confirmed,
                )
                for r in rows
            ]
            engine_assets.append(
                AssetInput(
                    id=asset.id,
                    name=asset.name,
                    publication_status=asset.publication_status,
                    in_market=(not markets) or True,
                )
            )
            run.edges_created += len(rows)

        engine = ChangePropagationEngine(changeset if not changeset.is_empty else None)
        impact_set = engine.compute(
            source_node=source_node,
            graph=graph,
            assets=engine_assets,
            edges_by_target=edges_by_target,
            node_labels=node_labels,
        )

        recommended_map = {
            "directly_affected": "repair",
            "probably_affected": "repair",
            "needs_review": "human_review",
            "safe": "none",
        }
        for it in impact_set.items:
            session.add(
                RecallImpact(
                    recall_event_id=recall.id,
                    asset_id=it.asset_id,
                    classification=it.classification,
                    impact_score=it.impact_score,
                    evidence_score=it.evidence_score,
                    score_components=it.components,
                    reasons=it.reasons,
                    strongest_path=it.strongest_path,
                    recommended_action=recommended_map[it.classification],
                    propagation_reason=it.propagation_reason,
                    causal_explanation=it.causal_explanation,
                    repair_requirement=it.repair_requirement,
                    distribution_risk=it.distribution_risk,
                )
            )

        # Minimal Repair Plan (spec section 18): compute the calculated savings.
        assets_by_id = {a.id: a for a in assets}
        planner_assets: list[PlannerAsset] = []
        for it in impact_set.items:
            if it.classification == "safe":
                continue
            a = assets_by_id.get(it.asset_id)
            if a is None:
                continue
            planner_assets.append(
                PlannerAsset(
                    id=a.id,
                    name=a.name,
                    parent_asset_id=a.parent_asset_id,
                    derivation_method=a.derivation_method,
                    needs_review=(it.classification == "needs_review"),
                )
            )
        plan_graph = MinimalRepairPlanner().plan(
            planner_assets, requires_generative=changeset.requires_generative_repair
        )
        recall.repair_plan_graph = plan_graph.as_dict()

        session.flush()
        # Impacts were inserted directly; refresh the relationship so callers
        # (review/repair/report) see the current rows rather than a stale cache.
        session.expire(recall, ["impacts"])
        _set_status(session, recall, recall_fsm.READY_FOR_REVIEW)
        audit(
            session,
            workspace.id,
            "recall.analysed",
            {
                "assets": len(assets),
                "operations_avoided": plan_graph.operations_avoided,
                "generative_operations": plan_graph.generative_operations,
            },
            recall_event_id=recall.id,
        )
        return run


# --- review --------------------------------------------------------------

def record_review_decision(
    session: Session,
    recall: RecallEvent,
    *,
    asset_id: str,
    decision: str,
    new_classification: str | None = None,
    reason: str = "",
    reviewed_by: str = "demo-user",
) -> ReviewDecision:
    rd = ReviewDecision(
        recall_event_id=recall.id,
        asset_id=asset_id,
        decision=decision,
        new_classification=new_classification,
        reason=reason,
        reviewed_by=reviewed_by,
    )
    session.add(rd)
    if new_classification:
        impact = session.execute(
            select(RecallImpact).where(
                RecallImpact.recall_event_id == recall.id, RecallImpact.asset_id == asset_id
            )
        ).scalar_one_or_none()
        if impact:
            impact.classification = new_classification
    audit(
        session, recall.workspace_id, "review.decision",
        {"asset_id": asset_id, "decision": decision}, actor=reviewed_by, recall_event_id=recall.id,
    )
    return rd


# --- repair --------------------------------------------------------------

def build_and_store_repair_plan(
    session: Session,
    storage: StorageBackend,
    workspace: Workspace,
    recall: RecallEvent,
    asset: Asset,
    version: AssetVersion,
    provider_name: str,
    model: str,
) -> RepairPlanRow:
    old_v = session.get(SourceOfTruthVersion, recall.old_version_id)
    new_v = session.get(SourceOfTruthVersion, recall.new_version_id)
    keys = ObjectKeys(workspace.id)
    new_version_id = new_id()
    instruction = build_repair_instruction(
        asset_type=asset.asset_type,
        asset_description=asset.description or asset.name,
        old_reference=old_v.label if old_v else "old",
        new_reference=new_v.label if new_v else "new",
        market=", ".join(recall.markets or []) or "global",
    )
    plan = RepairPlan(
        asset_id=asset.id,
        asset_version_id=version.id,
        recall_event_id=recall.id,
        changed_element=f"{old_v.label if old_v else ''} -> {new_v.label if new_v else ''}",
        editing_method="controlled_regeneration",
        provider=provider_name,
        model=model,
        operation_spec={"instruction": instruction, "width": version.width, "height": version.height},
        reference_inputs=[v for v in [version.b2_key, old_v.b2_key if old_v else None, new_v.b2_key if new_v else None] if v],
        expected_dimensions=(version.width, version.height) if version.width and version.height else None,
        validation_checks=["decodes", "dimensions_ok", "differs_from_original", "new_claim_present"],
        fallback_provider=None,
        retry_policy=DEFAULT_RETRY_POLICY,
        output_b2_key=keys.repaired_output(asset.id, new_version_id, "repaired.png"),
    )
    row = RepairPlanRow(
        recall_event_id=recall.id,
        asset_id=asset.id,
        asset_version_id=version.id,
        plan_version=plan.plan_version,
        idempotency_key=plan.idempotency_key,
        plan=plan.as_dict(),
    )
    session.add(row)
    session.flush()
    plan_key = keys.recall_plan(recall.id, row.id)
    stored = storage.put_bytes(plan_key, json.dumps(plan.as_dict(), indent=2).encode(), "application/json")
    row.b2_key = plan_key
    _track_object(session, workspace.id, stored, "repair_plan")
    audit(session, workspace.id, "repair.plan_created", {"asset_id": asset.id, "plan_id": row.id}, recall_event_id=recall.id)
    return row


def execute_repair_job(
    session: Session,
    storage: StorageBackend,
    workspace: Workspace,
    recall: RecallEvent,
    plan_row: RepairPlanRow,
    pipeline: GenblazePipeline,
) -> RepairJob:
    """Execute a repair through the Genblaze pipeline and persist an immutable
    new version + manifest. Never fabricates output on provider failure."""
    asset = session.get(Asset, plan_row.asset_id)
    version = session.get(AssetVersion, plan_row.asset_version_id)
    if asset is None or version is None:
        raise ValueError("repair plan references a missing asset or version")
    plan = plan_row.plan

    # Idempotency: reuse existing successful job.
    existing = session.execute(
        select(RepairJob).where(
            RepairJob.idempotency_key == plan_row.idempotency_key,
            RepairJob.status == "completed",
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    job = RepairJob(
        recall_event_id=recall.id,
        repair_plan_id=plan_row.id,
        asset_id=asset.id,
        idempotency_key=plan_row.idempotency_key,
        status="running",
        stage="provider_invocation",
    )
    session.add(job)
    session.flush()

    with log_context(workspace_id=workspace.id, recall_id=recall.id, asset_id=asset.id, job_id=job.id):
        original_bytes = storage.get_bytes(version.b2_key)
        old_v = session.get(SourceOfTruthVersion, recall.old_version_id)
        new_v = session.get(SourceOfTruthVersion, recall.new_version_id)
        refs = [original_bytes]
        for ref_v in (old_v, new_v):
            if ref_v and ref_v.b2_key and storage.exists(ref_v.b2_key):
                refs.append(storage.get_bytes(ref_v.b2_key))

        request = GenerationRequest(
            prompt=plan["operation_spec"]["instruction"],
            width=version.width or 1024,
            height=version.height or 1024,
            reference_images=refs,
            operation="edit",
        )

        try:
            execution = pipeline.run(request, job_id=job.id)
        except ProviderConfigError as exc:
            job.status = "failed"
            job.error_category = exc.category
            job.error_detail = str(exc)
            audit(session, workspace.id, "repair.disabled", {"reason": str(exc)}, recall_event_id=recall.id)
            return job

        job.attempts = execution.attempts
        gen = GenerationRun(
            repair_job_id=job.id,
            provider=execution.provider_used,
            model=execution.result.model if execution.result else plan["model"],
            genblaze_pipeline=execution.pipeline_id,
            attempts=execution.attempts,
            stages=[s.as_dict() for s in execution.stages],
        )
        session.add(gen)

        if execution.result is None:
            job.status = "failed"
            job.error_category = "provider_unavailable"
            job.error_detail = "all providers exhausted; inputs and plan preserved"
            audit(session, workspace.id, "repair.failed", {"asset_id": asset.id}, recall_event_id=recall.id)
            return job

        usage_metering.record_usage(
            session,
            workspace,
            usage_metering.EVENT_GENERATION_OPERATION,
            detail={"provider": execution.provider_used, "asset_id": asset.id},
        )
        output = execution.result.image_bytes
        keys = ObjectKeys(workspace.id)
        new_version_id = new_id()

        # validate BEFORE marking complete
        job.stage = "validation"
        val = validate_repaired_image(
            output,
            original_bytes=original_bytes,
            original_phash=version.phash,
            expected_dimensions=(version.width, version.height) if version.width and version.height else None,
            expected_mime="image/png",
            new_claim_text=new_v.claim_text if new_v else None,
            deprecated_claim_text=old_v.claim_text if old_v else None,
            extracted_text=extract_text(output),
        )

        # store new immutable version (original never overwritten)
        out_key = keys.repaired_output(asset.id, new_version_id, "repaired.png")
        stored = storage.put_bytes(out_key, output, "image/png", metadata={"sha256": val.output_sha256 or ""})
        _track_object(session, workspace.id, stored, "repaired_output")

        new_version = AssetVersion(
            id=new_version_id,
            asset_id=asset.id,
            version=(version.version + 1),
            origin="repaired",
            sha256=val.output_sha256 or sha256_bytes(output),
            phash=perceptual_hash_bytes(output),
            width=val.output_dimensions[0] if val.output_dimensions else version.width,
            height=val.output_dimensions[1] if val.output_dimensions else version.height,
            content_type="image/png",
            byte_size=len(output),
            b2_key=out_key,
            parent_version_id=version.id,
        )
        session.add(new_version)
        session.flush()

        val_key = keys.repaired_validation(asset.id, new_version_id)
        vstored = storage.put_bytes(val_key, json.dumps(val.as_dict(), indent=2).encode(), "application/json")
        _track_object(session, workspace.id, vstored, "validation")
        session.add(
            ValidationResultRow(
                repair_job_id=job.id,
                asset_version_id=new_version_id,
                passed=val.passed,
                requires_human_review=val.requires_human_review,
                checks=val.checks,
                notes=val.notes,
                b2_key=val_key,
            )
        )

        manifest = build_repair_manifest(
            recall_event_id=recall.id,
            source_of_truth_item_id=recall.source_item_id,
            source_of_truth_version_id=recall.new_version_id,
            original_asset_id=asset.id,
            original_asset_version_id=version.id,
            original_sha256=version.sha256,
            original_b2_key=version.b2_key,
            new_asset_version_id=new_version_id,
            output_sha256=new_version.sha256,
            output_b2_key=out_key,
            provider=execution.provider_used,
            model=gen.model,
            genblaze_pipeline=execution.pipeline_id,
            operation_spec=plan["operation_spec"],
            caused_by=f"recall:{recall.id}",
            validation=val.as_dict(),
        )
        man_key = keys.repaired_manifest(asset.id, new_version_id)
        mstored = storage.put_bytes(man_key, json.dumps(manifest, indent=2).encode(), "application/json")
        new_version.manifest_b2_key = man_key
        gen.manifest_b2_key = man_key
        _track_object(session, workspace.id, mstored, "manifest")

        job.result_version_id = new_version_id
        if val.requires_human_review:
            job.status = "requires_review"
            job.stage = "requires_human_review"
        else:
            job.status = "completed"
            job.stage = "completed"
        audit(
            session, workspace.id, "repair.completed",
            {"asset_id": asset.id, "new_version_id": new_version_id, "validation_passed": val.passed},
            recall_event_id=recall.id,
        )
        return job


def approve_and_repair(
    session: Session,
    storage: StorageBackend,
    workspace: Workspace,
    recall: RecallEvent,
    pipeline: GenblazePipeline,
    *,
    provider_name: str,
    model: str,
    asset_ids: list[str] | None = None,
    max_repairs: int | None = None,
) -> list[RepairJob]:
    """Approve high-confidence impacts and run repairs through the pipeline.

    Respects the demo repair cap (directive section 25). Sets the recall status
    through APPROVED -> REPAIRING -> COMPLETED / PARTIALLY_COMPLETED.
    """
    if recall.status == recall_fsm.READY_FOR_REVIEW:
        _set_status(session, recall, recall_fsm.APPROVED)
    if recall.status == recall_fsm.APPROVED:
        _set_status(session, recall, recall_fsm.REPAIRING)

    impacts = [
        i for i in recall.impacts
        if i.classification in ("directly_affected", "probably_affected")
    ]
    if asset_ids is not None:
        impacts = [i for i in impacts if i.asset_id in asset_ids]
    if max_repairs is not None:
        impacts = impacts[:max_repairs]

    jobs: list[RepairJob] = []
    for impact in impacts:
        asset = session.get(Asset, impact.asset_id)
        if asset is None:
            continue
        version = session.execute(
            select(AssetVersion)
            .where(AssetVersion.asset_id == asset.id, AssetVersion.origin == "uploaded")
            .order_by(AssetVersion.version.desc())
        ).scalars().first()
        if version is None:
            continue
        record_review_decision(
            session, recall, asset_id=asset.id, decision="approve", reason="auto-approved high confidence"
        )
        plan_row = build_and_store_repair_plan(
            session, storage, workspace, recall, asset, version, provider_name, model
        )
        job = execute_repair_job(session, storage, workspace, recall, plan_row, pipeline)
        jobs.append(job)
        session.flush()

    succeeded = [j for j in jobs if j.status == "completed"]
    failed = [j for j in jobs if j.status == "failed"]
    if jobs and not failed:
        _set_status(session, recall, recall_fsm.COMPLETED)
    elif succeeded:
        _set_status(session, recall, recall_fsm.PARTIALLY_COMPLETED)
    elif failed:
        # nothing succeeded; keep repairing state recoverable
        _set_status(session, recall, recall_fsm.PARTIALLY_COMPLETED)
    return jobs


def build_report(session: Session, workspace: Workspace, recall: RecallEvent, *, elapsed_seconds: float = 0.0):
    """Assemble the final RecallReport from persisted data (directive section 11)."""
    from rusted_recall.reporting import RecallReport

    impacts = list(recall.impacts)
    jobs = session.execute(
        select(RepairJob).where(RepairJob.recall_event_id == recall.id)
    ).scalars().all()
    objects = session.execute(
        select(ArtifactObject).where(ArtifactObject.workspace_id == workspace.id)
    ).scalars().all()
    gens = session.execute(select(GenerationRun)).scalars().all()
    audits = session.execute(
        select(AuditEvent).where(AuditEvent.recall_event_id == recall.id).order_by(AuditEvent.created_at)
    ).scalars().all()
    item = session.get(SourceOfTruthItem, recall.source_item_id)
    reviews = session.execute(
        select(ReviewDecision).where(ReviewDecision.recall_event_id == recall.id)
    ).scalars().all()

    def count(cls: str) -> int:
        return sum(1 for i in impacts if i.classification == cls)

    report = RecallReport(
        recall_event_id=recall.id,
        workspace_name=workspace.name,
        source_of_truth=item.name if item else "",
        reason=recall.reason,
        total_assets_scanned=len(impacts),
        directly_affected=count("directly_affected"),
        probably_affected=count("probably_affected"),
        needs_review=count("needs_review"),
        safe=count("safe"),
        repair_requested=len(jobs),
        repair_succeeded=sum(1 for j in jobs if j.status == "completed"),
        repair_failed=sum(1 for j in jobs if j.status == "failed"),
        repair_requires_review=sum(1 for j in jobs if j.status == "requires_review"),
        elapsed_seconds=elapsed_seconds,
        provider_operations=sum(g.attempts for g in gens),
        b2_objects_created=len(objects),
        review_decisions=[{"asset_id": r.asset_id, "decision": r.decision, "reason": r.reason} for r in reviews],
        audit_timeline=[
            {"at": a.created_at.isoformat(), "event": a.event, "detail": json.dumps(a.detail)}
            for a in audits
        ],
        integrity_hashes={o.b2_key: o.sha256 or "" for o in objects if o.sha256},
    )
    return report
