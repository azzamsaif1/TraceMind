"""Thin presentation adapter for the Judge Experience (spec Phase 2).

This module contains **no domain logic**. It only *reads* persisted Rusted
Recall state (recalls, impacts, assets, versions, repair jobs, audit events and
opportunities) and shapes it into a plain view-model for ``judge_recall.html``.
Every field is real or explicitly absent (``None``) — never fabricated. The
Judge UI renders ``—`` / a visual-only state whenever a value is absent.

The engine (dependency analysis, scoring, planner, repair, storage, provider,
opportunities) is reached exclusively through the existing services layer.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from rusted_recall.models import (
    Asset,
    AssetVersion,
    AuditEvent,
    Opportunity,
    RecallEvent,
    RecallImpact,
    RepairJob,
    SourceOfTruthItem,
    SourceOfTruthVersion,
)

# --- static, honest presentation maps (no data invented) ------------------

# Icon by asset type substring — a purely visual fallback when no preview
# exists. It never changes the underlying classification/status.
_ICON_RULES: list[tuple[tuple[str, ...], str]] = [
    (("package", "packaging", "label", "product"), "📦"),
    (("instagram", "social", "square", "story"), "📱"),
    (("banner", "hero", "display", "ad"), "🖼️"),
    (("video", "reel", "motion"), "🎬"),
    (("marketplace", "listing", "shop", "commerce"), "🛒"),
    (("logo", "mark", "icon"), "🔷"),
    (("email", "newsletter"), "✉️"),
]

# Real classification / job status -> the CSS node status class the reference
# design defines (idle | affected | critical | review | safe | repaired).
_NODE_STATUS: dict[str, str] = {
    "directly_affected": "critical",
    "probably_affected": "affected",
    "needs_review": "review",
    "requires_review": "review",
    "review": "review",
    "safe": "safe",
    "unaffected": "safe",
    "repaired": "repaired",
    "completed": "repaired",
    "failed": "critical",
    "blocked": "review",
    "draft": "idle",
    "queued": "idle",
    "analysing": "idle",
    "running": "idle",
}

# recall.status -> "Current Operation" copy (spec section: current op mapping).
CURRENT_OP: dict[str, str] = {
    "draft": "Ready to analyse",
    "analysing": "Tracing dependencies",
    "ready_for_review": "Review required",
    "approved": "Repair plan approved",
    "repairing": "Executing minimal repair",
    "partially_completed": "Repair needs attention",
    "completed": "Recall verified",
    "failed": "Repair failed",
    "blocked": "Provider capability blocked",
}

# recall.status -> primary action (label + machine action key).
PRIMARY_ACTION: dict[str, dict] = {
    "draft": {"label": "Start analysis", "action": "analyse", "enabled": True},
    "analysing": {"label": "Analysing…", "action": "none", "enabled": False},
    "ready_for_review": {"label": "Review affected asset", "action": "review", "enabled": True},
    "approved": {"label": "Execute minimal repair", "action": "repair", "enabled": True},
    "repairing": {"label": "Repairing…", "action": "none", "enabled": False},
    "partially_completed": {"label": "Inspect remaining issue", "action": "inspect", "enabled": True},
    "completed": {"label": "Discover Verified Opportunities", "action": "discover", "enabled": True},
    "failed": {"label": "Inspect failure", "action": "inspect", "enabled": True},
    "blocked": {"label": "Inspect blocked repair", "action": "inspect", "enabled": True},
}

# Audit event name -> human timeline label. Only *translates* persisted events;
# never invents a timeline entry (spec: timeline from persisted audit events).
_TIMELINE_LABELS: dict[str, str] = {
    "recall.created": "Recall created",
    "recall.analysed": "Dependency graph built",
    "impact.classified": "Impact classified",
    "review.decision": "Review decision recorded",
    "repair.planned": "Minimal repair planned",
    "repair.queued": "Repair queued",
    "repair.started": "Repair started",
    "repair.completed": "Repair completed",
    "repair.failed": "Repair failed",
    "repair.native": "Native repair executed",
    "validation.completed": "Validation completed",
    "storage.verified": "Stored & verified on B2",
    "opportunity.discovery.started": "Opportunity discovery started",
    "opportunity.candidate.evaluated": "Opportunity candidate evaluated",
    "opportunity.verified": "Verified opportunity created",
    "opportunity.blocked": "Opportunity blocked",
    "opportunity.rejected": "Opportunity candidate rejected",
    "opportunity.execution.started": "Opportunity execution started",
    "opportunity.execution.completed": "Opportunity executed",
    "opportunity.execution.failed": "Opportunity execution incomplete",
}


def _icon(asset: Asset) -> str:
    hay = f"{asset.asset_type} {asset.name}".lower()
    for keys, icon in _ICON_RULES:
        if any(k in hay for k in keys):
            return icon
    return "🗂️"


def _hhmm(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def _uploaded(session: Session, asset_id: str) -> AssetVersion | None:
    return session.execute(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id, AssetVersion.origin == "uploaded")
        .order_by(AssetVersion.version)
    ).scalars().first()


def _repaired(session: Session, asset_id: str) -> AssetVersion | None:
    return session.execute(
        select(AssetVersion)
        .where(AssetVersion.asset_id == asset_id, AssetVersion.origin == "repaired")
        .order_by(AssetVersion.version.desc())
    ).scalars().first()


def _job(session: Session, recall_id: str, asset_id: str) -> RepairJob | None:
    return session.execute(
        select(RepairJob)
        .where(RepairJob.recall_event_id == recall_id, RepairJob.asset_id == asset_id)
        .order_by(RepairJob.created_at.desc())
    ).scalars().first()


def _node_status(classification: str | None, job: RepairJob | None) -> str:
    """Truthful node colour: a finished/failed job wins over classification."""
    if job is not None:
        if job.status == "completed":
            return "repaired"
        if job.status == "failed":
            return "critical"
        if job.status in ("queued", "running"):
            return "idle"
    return _NODE_STATUS.get((classification or "").lower(), "idle")


def _asset_row(session: Session, recall: RecallEvent, imp: RecallImpact) -> dict | None:
    asset = session.get(Asset, imp.asset_id)
    if asset is None:
        return None
    up = _uploaded(session, asset.id)
    rep = _repaired(session, asset.id)
    job = _job(session, recall.id, asset.id)
    parent = session.get(Asset, asset.parent_asset_id) if asset.parent_asset_id else None
    strongest = imp.strongest_path or {}
    dep_path = strongest.get("path") or strongest.get("nodes") or []
    return {
        "id": asset.id,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "icon": _icon(asset),
        "classification": imp.classification,
        "node_status": _node_status(imp.classification, job),
        "impact_score": round(imp.impact_score, 2) if imp.impact_score is not None else None,
        "evidence_score": round(imp.evidence_score, 2) if imp.evidence_score else None,
        # Confidence is NOT a persisted field -> honestly absent.
        "confidence": None,
        "causal_reason": imp.causal_explanation or imp.propagation_reason or None,
        "dependency_path": dep_path if isinstance(dep_path, list) else [],
        "score_components": imp.score_components or {},
        "reasons": imp.reasons or [],
        "repair_requirement": imp.repair_requirement or None,
        "derivation_method": asset.derivation_method,
        "parent_name": parent.name if parent else None,
        "job_status": job.status if job else None,
        "job_stage": job.stage if job else None,
        "error_category": job.error_category if job else None,
        "versions": (f"v{up.version} → v{rep.version}" if up and rep
                     else (f"v{up.version}" if up else None)),
        "b2_key": (rep.b2_key if rep else (up.b2_key if up else None)),
        "sha256": (rep.sha256 if rep else (up.sha256 if up else None)),
        "before_url": (f"/obj?key={up.b2_key}" if up and up.b2_key else None),
        "after_url": (f"/obj?key={rep.b2_key}" if rep and rep.b2_key else None),
        "dimensions": (f"{rep.width}×{rep.height}" if rep and rep.width
                       else (f"{up.width}×{up.height}" if up and up.width else None)),
    }


def _timeline(session: Session, recall_id: str) -> list[dict]:
    events = session.execute(
        select(AuditEvent)
        .where(AuditEvent.recall_event_id == recall_id)
        .order_by(AuditEvent.created_at)
    ).scalars().all()
    out = []
    for e in events:
        label = _TIMELINE_LABELS.get(e.event)
        if label is None:
            # Unknown but real event: prettify its name, never drop or invent.
            label = e.event.replace(".", " ").replace("_", " ").capitalize()
        out.append({"time": _hhmm(e.created_at), "event": label, "raw": e.event})
    return out


def opportunities_view(session: Session, recall_id: str) -> list[dict]:
    opps = session.execute(
        select(Opportunity)
        .where(Opportunity.recall_event_id == recall_id)
        .order_by(Opportunity.created_at)
    ).scalars().all()
    out = []
    for o in opps:
        ev = o.evidence or {}
        out.append({
            "id": o.id,
            "title": o.title,
            "rationale": o.rationale,
            "status": o.status,
            "kind": o.kind,
            "feasibility_state": o.feasibility_state,
            "native_operations": o.native_operations,
            "generative_operations": o.generative_operations,
            "blocked_operations": o.blocked_operations,
            "executed_operations": o.executed_operations,
            "causal_path": ev.get("causal_path"),
            "counterfactual": ev.get("counterfactual"),
            "why_enabled": ev.get("why_enabled"),
            "executable": o.status == "verified",
            "result": o.result or None,
        })
    return out


def _summary(rows: list[dict], opportunities: list[dict], recall: RecallEvent) -> dict:
    affected = [r for r in rows if r["node_status"] in ("critical", "affected")]
    repaired = [r for r in rows if r["job_status"] == "completed"]
    review = [r for r in rows if r["node_status"] == "review"]
    safe = [r for r in rows if r["node_status"] == "safe"]
    # Operations avoided = downstream derivatives NOT regenerated because a
    # deterministic/native path or safe classification made generation
    # unnecessary. Counted only from real rows.
    avoided = sum(
        1 for r in rows
        if r["derivation_method"] in ("crop", "resize")
        or (r["node_status"] == "safe" and r["dependency_path"])
    )
    verified_opps = [o for o in opportunities if o["status"] in ("verified", "executed")]
    return {
        "assets_analysed": len(rows),
        "affected": len(affected),
        "repaired": len(repaired),
        "requiring_review": len(review),
        "safe": len(safe),
        "operations_avoided": avoided,
        "verified_opportunities": len(verified_opps),
        # B2/verification is only claimed when a repaired version actually
        # carries a stored key + hash (see rows). Never asserted otherwise.
        "storage_verified": any(r["job_status"] == "completed" and r["b2_key"] and r["sha256"]
                                for r in rows),
        "verification_state": recall.status,
    }


def build_view_model(session: Session, recall: RecallEvent) -> dict:
    item = session.get(SourceOfTruthItem, recall.source_item_id)
    old_v = session.get(SourceOfTruthVersion, recall.old_version_id)
    new_v = session.get(SourceOfTruthVersion, recall.new_version_id)

    impacts = session.execute(
        select(RecallImpact)
        .where(RecallImpact.recall_event_id == recall.id)
        .order_by(RecallImpact.impact_score.desc())
    ).scalars().all()
    rows = [r for imp in impacts if (r := _asset_row(session, recall, imp)) is not None]
    opportunities = opportunities_view(session, recall.id)

    primary = PRIMARY_ACTION.get(recall.status, {"label": "View recall", "action": "none", "enabled": False})
    # Only offer discovery once the recall is genuinely verified.
    if primary["action"] == "discover" and recall.status not in ("completed", "partially_completed"):
        primary = {"label": "View verified result", "action": "none", "enabled": False}

    return {
        "recall_id": recall.id,
        "status": recall.status,
        "current_operation": CURRENT_OP.get(recall.status, "—"),
        "primary_action": primary,
        "source": {
            "name": item.name if item else "Source of Truth",
            "current_claim": (new_v.claim_text or new_v.label) if new_v else "—",
            "previous_claim": (old_v.claim_text or old_v.label) if old_v else None,
            "reason": recall.reason or None,
        },
        "created_at": recall.created_at.isoformat() if recall.created_at else None,
        "assets": rows,
        "timeline": _timeline(session, recall.id),
        "opportunities": opportunities,
        "summary": _summary(rows, opportunities, recall),
    }


def asset_detail(session: Session, recall: RecallEvent, asset_id: str) -> dict | None:
    imp = session.execute(
        select(RecallImpact).where(
            RecallImpact.recall_event_id == recall.id,
            RecallImpact.asset_id == asset_id,
        )
    ).scalars().first()
    if imp is None:
        return None
    return _asset_row(session, recall, imp)


def evidence_bundle(session: Session, recall: RecallEvent) -> dict:
    """Answers: what changed, why each asset mattered, what was repaired, what
    was avoided, what version was created, how it was verified, what remains."""
    vm = build_view_model(session, recall)
    return {
        "recall_id": recall.id,
        "changeset": recall.changeset or {},
        "repair_plan": recall.repair_plan_graph or {},
        "summary": vm["summary"],
        "assets": vm["assets"],
        "opportunities": vm["opportunities"],
        "timeline": vm["timeline"],
    }
