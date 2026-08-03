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
    "recall.analysed": "Impact analysis completed",
    "impact.classified": "Impact classified",
    "review.decision": "Review decision recorded",
    "repair.planned": "Minimal repair planned",
    "repair.plan_created": "Minimal repair planned",
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
    "recall.replayed": "Replay viewed",
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


# Human labels for repair methods (spec section 17 "Repair method").
_METHOD_LABELS: dict[str, str] = {
    "text_overlay": "Text overlay",
    "deterministic_crop": "Deterministic crop",
    "deterministic_resize": "Deterministic resize",
    "crop": "Deterministic crop",
    "resize": "Deterministic resize",
    "generative_edit": "Generative edit",
    "controlled_regeneration": "Controlled regeneration",
    "manual_review": "Manual review",
}

# Classifications that count as "affected" (spec section 14). Kept independent
# of the current node colour so completing a repair never erases the historical
# impact (spec section 13 acceptance).
_AFFECTED_CLASSES = frozenset({"directly_affected", "probably_affected", "needs_review", "requires_review"})
_REVIEW_CLASSES = frozenset({"needs_review", "requires_review"})


def _impact_band(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 0.55:
        return "High"
    if score >= 0.25:
        return "Medium"
    if score > 0:
        return "Low"
    return "None"


def _node_name(session: Session, token: str) -> str | None:
    """Resolve a graph node token (``asset:<id>`` / ``sot:<id>`` / bare id/name)
    to a human-readable name. Returns None when it cannot be resolved."""
    if not token:
        return None
    raw = str(token)
    if raw.startswith("asset:"):
        a = session.get(Asset, raw.split(":", 1)[1])
        return a.name if a else None
    if raw.startswith("sot:"):
        it = session.get(SourceOfTruthItem, raw.split(":", 1)[1])
        return it.name if it else None
    a = session.get(Asset, raw)
    if a is not None:
        return a.name
    return raw


def _job_status_label(job: RepairJob | None, classification: str | None) -> str:
    """Truthful, human job status — never a bare dash (spec section 17)."""
    if job is not None:
        return {
            "completed": "Completed",
            "failed": "Failed",
            "queued": "Queued",
            "running": "Repairing",
            "requires_review": "Awaiting review",
        }.get(job.status, job.status)
    cls = (classification or "").lower()
    if cls in ("safe", "unaffected"):
        return "Verified safe"
    if cls in _REVIEW_CLASSES:
        return "Awaiting review decision"
    if cls in _AFFECTED_CLASSES:
        return "Awaiting review decision"
    return "No action required"


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
    dep_path = dep_path if isinstance(dep_path, list) else []
    # Human-readable dependency chain (spec section 19): resolve every graph
    # node token to a real name, appending the derivation parent when the raw
    # path is only source -> asset so the derivative lineage is visible.
    dep_names: list[str] = []
    for tok in dep_path:
        nm = _node_name(session, str(tok))
        if nm:
            dep_names.append(nm)
    if parent and parent.name and parent.name not in dep_names:
        dep_names.insert(max(0, len(dep_names) - 1), parent.name)
    # Before/After semantic state (spec section 18) — never present a missing
    # repaired version as if a repair happened.
    if rep is not None:
        preview_state = "repaired"
    elif (imp.classification or "").lower() in ("safe", "unaffected"):
        preview_state = "safe"
    elif (imp.classification or "").lower() in _REVIEW_CLASSES:
        preview_state = "pending_review"
    elif (imp.classification or "").lower() in _AFFECTED_CLASSES:
        preview_state = "pending_repair"
    else:
        preview_state = "none"
    method = asset.derivation_method or imp.repair_requirement
    return {
        "id": asset.id,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "icon": _icon(asset),
        "classification": imp.classification,
        "classification_label": (imp.classification or "").replace("_", " ").title() or None,
        "node_status": _node_status(imp.classification, job),
        "impact_score": round(imp.impact_score, 2) if imp.impact_score is not None else None,
        "impact_percent": round(imp.impact_score * 100) if imp.impact_score is not None else None,
        "impact_band": _impact_band(imp.impact_score),
        "evidence_score": round(imp.evidence_score, 2) if imp.evidence_score else None,
        # Confidence is NOT a persisted field -> honestly absent.
        "confidence": None,
        "causal_reason": imp.causal_explanation or imp.propagation_reason or None,
        "dependency_path": dep_path,
        "dependency_path_names": dep_names,
        "job_status_label": _job_status_label(job, imp.classification),
        "repair_method_label": (_METHOD_LABELS.get(method) if method else None),
        "preview_state": preview_state,
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
        # Real repaired-version timestamp for the before/after gallery (spec
        # "Before/After: Timestamp"). Absent until a repair actually ran.
        "repaired_at": rep.created_at.isoformat() if rep and rep.created_at else None,
        "before_url": (f"/obj?key={up.b2_key}" if up and up.b2_key else None),
        "after_url": (f"/obj?key={rep.b2_key}" if rep and rep.b2_key else None),
        "dimensions": (f"{rep.width}×{rep.height}" if rep and rep.width
                       else (f"{up.width}×{up.height}" if up and up.width else None)),
    }


# Low-level opportunity events collapsed into one grouped timeline row (spec
# section 16) — the raw events remain untouched in the audit log / evidence.
_DISCOVERY_FAMILY = frozenset({
    "opportunity.candidate.evaluated", "opportunity.verified",
    "opportunity.blocked", "opportunity.rejected",
})
# recall.status transitions worth surfacing to a judge (the rest are implied).
_STATUS_STAGE: dict[str, str] = {
    "repairing": "Repair started",
    "completed": "Recall verified",
    "partially_completed": "Repair needs attention",
    "failed": "Repair failed",
    "blocked": "Provider capability blocked",
}
_DECISION_VERB = {"approve": "approved", "exclude": "excluded", "mark_safe": "marked safe"}


def _timeline(session: Session, recall_id: str) -> list[dict]:
    """Curated, judge-readable timeline over the raw audit log.

    Repeated low-level opportunity-discovery events are summarised into a single
    grouped row (candidates evaluated / verified / rejected). Review decisions
    and repairs are rendered with real asset names. No raw AuditEvent record is
    deleted — the evidence modal still exposes every event verbatim.
    """
    events = session.execute(
        select(AuditEvent)
        .where(AuditEvent.recall_event_id == recall_id)
        .order_by(AuditEvent.created_at)
    ).scalars().all()

    out: list[dict] = []
    group: dict | None = None
    seen_reviews: set[tuple[str, str]] = set()

    def flush_group() -> None:
        nonlocal group
        if group is None:
            return
        detail = (f"{group['evaluated']} candidate"
                  f"{'s' if group['evaluated'] != 1 else ''} evaluated · "
                  f"{group['verified']} verified · {group['rejected']} rejected")
        out.append({"time": group["time"], "event": "Opportunity discovery completed",
                    "detail": detail, "raw": "opportunity.discovery"})
        group = None

    for e in events:
        ev = e.event
        detail = e.detail if isinstance(e.detail, dict) else {}
        if ev == "opportunity.discovery.started":
            flush_group()
            group = {"time": _hhmm(e.created_at), "evaluated": 0, "verified": 0,
                     "blocked": 0, "rejected": 0}
            continue
        if ev in _DISCOVERY_FAMILY:
            if group is None:
                group = {"time": _hhmm(e.created_at), "evaluated": 0, "verified": 0,
                         "blocked": 0, "rejected": 0}
            if ev == "opportunity.candidate.evaluated":
                group["evaluated"] += 1
            elif ev == "opportunity.verified":
                group["verified"] += 1
            elif ev == "opportunity.blocked":
                group["blocked"] += 1
            elif ev == "opportunity.rejected":
                group["rejected"] += 1
            continue
        flush_group()

        label: str | None
        if ev == "recall.status":
            label = _STATUS_STAGE.get(detail.get("status", ""))
            if label is None:
                continue  # implied transition — omit noise
        elif ev == "review.decision":
            key = (detail.get("asset_id", ""), detail.get("decision", ""))
            if key in seen_reviews:
                continue  # same decision recorded twice by approve->repair path
            seen_reviews.add(key)
            nm = _node_name(session, detail.get("asset_id", "")) or "Asset"
            verb = _DECISION_VERB.get(detail.get("decision", ""), detail.get("decision", "reviewed"))
            label = f"{nm} {verb}"
        elif ev in ("repair.completed", "repair.native"):
            rnm = _node_name(session, detail.get("asset_id", ""))
            label = f"{rnm} repaired" if rnm else _TIMELINE_LABELS.get(ev, "Repair completed")
        elif ev == "repair.failed":
            fnm = _node_name(session, detail.get("asset_id", ""))
            label = f"{fnm} repair failed" if fnm else "Repair failed"
        else:
            label = _TIMELINE_LABELS.get(ev)
            if label is None:
                label = ev.replace(".", " ").replace("_", " ").capitalize()

        row = {"time": _hhmm(e.created_at), "event": label, "raw": ev}
        # Collapse consecutive identical labels (e.g. the review decision recorded
        # twice by the approve->repair path).
        if out and out[-1]["event"] == label and out[-1].get("raw") == ev:
            continue
        out.append(row)
    flush_group()
    return out


def discovery_summary(session: Session, recall_id: str) -> dict | None:
    """The outcome of the most recent opportunity-discovery pass, derived from
    persisted audit events (spec 6/23): candidates evaluated, verified, rejected
    and the recorded rejection reasons. Returns None if discovery never ran."""
    events = session.execute(
        select(AuditEvent)
        .where(AuditEvent.recall_event_id == recall_id)
        .order_by(AuditEvent.created_at)
    ).scalars().all()
    # locate the last discovery pass
    start = None
    for i, e in enumerate(events):
        if e.event == "opportunity.discovery.started":
            start = i
    if start is None:
        return None
    evaluated = verified = rejected = blocked = 0
    rejections: list[dict] = []
    for e in events[start:]:
        if e.event == "opportunity.discovery.started" and e is not events[start]:
            break
        d = e.detail if isinstance(e.detail, dict) else {}
        if e.event == "opportunity.candidate.evaluated":
            evaluated += 1
        elif e.event == "opportunity.verified":
            verified += 1
        elif e.event == "opportunity.blocked":
            blocked += 1
        elif e.event == "opportunity.rejected":
            rejected += 1
            rejections.append({
                "asset": _node_name(session, d.get("asset_id", "")) or "candidate",
                "reason": d.get("reason"),
            })
    return {"evaluated": evaluated, "verified": verified, "rejected": rejected,
            "blocked": blocked, "rejections": rejections}


def opportunities_view(session: Session, recall_id: str) -> list[dict]:
    opps = session.execute(
        select(Opportunity)
        .where(Opportunity.recall_event_id == recall_id)
        .order_by(Opportunity.created_at)
    ).scalars().all()
    out = []
    for o in opps:
        ev = o.evidence or {}
        causal = ev.get("causal_path") or []
        target_name = parent_name = None
        for node in causal if isinstance(causal, list) else []:
            role = node.get("role") if isinstance(node, dict) else None
            nm = _node_name(session, str(node.get("node", ""))) if isinstance(node, dict) else None
            if role == "downstream_derivative":
                target_name = nm
            elif role == "repaired_parent":
                parent_name = nm
        # Human-readable causal chain (spec section 19).
        causal_names = []
        for n in (causal if isinstance(causal, list) else []):
            if not isinstance(n, dict):
                continue
            tok = str(n.get("node", ""))
            if "source" in tok.lower():
                causal_names.append("Source of Truth")
            else:
                causal_names.append(_node_name(session, tok) or tok)
        kind_label = (o.kind or "").replace("_", " ").title() or None
        out.append({
            "id": o.id,
            "title": o.title,
            "rationale": o.rationale,
            "status": o.status,
            "status_label": (o.status or "").replace("_", " ").title() or None,
            "kind": o.kind,
            "kind_label": kind_label,
            "target_name": target_name,
            "parent_name": parent_name,
            "feasibility_state": o.feasibility_state,
            "native_operations": o.native_operations,
            "generative_operations": o.generative_operations,
            "blocked_operations": o.blocked_operations,
            "executed_operations": o.executed_operations,
            "causal_path": causal,
            "causal_path_names": [n for n in causal_names if n],
            "counterfactual": ev.get("counterfactual"),
            "why_enabled": ev.get("why_enabled"),
            "dedup_ref": (o.dedup_key[:12] if o.dedup_key else None),
            "executable": o.status == "verified",
            "result": o.result or None,
        })
    return out


def _summary(rows: list[dict], opportunities: list[dict], recall: RecallEvent) -> dict:
    # Affected/review derive from the persisted CLASSIFICATION, not the current
    # node colour, so completing a repair never resets these to 0 (spec 13/14).
    affected = [r for r in rows if (r["classification"] or "").lower() in _AFFECTED_CLASSES]
    review = [r for r in rows if (r["classification"] or "").lower() in _REVIEW_CLASSES]
    safe = [r for r in rows if (r["classification"] or "").lower() in ("safe", "unaffected")]
    # Repaired = a completed job that produced a real result version (spec 14).
    repaired = [r for r in rows if r["job_status"] == "completed" and r.get("after_url")]
    # Operations avoided = the engine's own minimal-repair-plan figure (spec 14)
    # — generative operations replaced by deterministic/native reconstruction.
    # Never derived from arbitrary asset-count differences.
    plan = recall.repair_plan_graph or {}
    avoided = plan.get("operations_avoided")
    if not isinstance(avoided, int):
        avoided = 0
    # Impact aggregate (spec 13): the strongest persisted impact score across
    # the analysed assets. Stable across repair; explains what the % means.
    scores = [r["impact_score"] for r in rows if r["impact_score"] is not None]
    top = max(scores) if scores else None
    verified_opps = [o for o in opportunities if o["status"] in ("verified", "executed")]
    return {
        "assets_analysed": len(rows),
        "affected": len(affected),
        "repaired": len(repaired),
        "requiring_review": len(review),
        "safe": len(safe),
        "operations_avoided": avoided,
        "verified_opportunities": len(verified_opps),
        "impact_percent": round(top * 100) if top is not None else 0,
        "impact_band": _impact_band(top),
        # B2/verification is only claimed when a repaired version actually
        # carries a stored key + hash (see rows). Never asserted otherwise.
        "storage_verified": any(r["job_status"] == "completed" and r["b2_key"] and r["sha256"]
                                for r in rows),
        "verification_state": recall.status,
    }


def _counts(session: Session, recall_id: str) -> tuple[int, int]:
    """Engine-driven Evidence Count and Replay Count, both read straight from
    the append-only audit log so they are identical after refresh/reopen and
    can never be hard-coded. Evidence Count = every recorded audit event for
    the recall; Replay Count = the persisted ``recall.replayed`` events."""
    names = session.execute(
        select(AuditEvent.event).where(AuditEvent.recall_event_id == recall_id)
    ).scalars().all()
    evidence_count = len(names)
    replay_count = sum(1 for n in names if n == "recall.replayed")
    return evidence_count, replay_count


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

    summary = _summary(rows, opportunities, recall)
    evidence_count, replay_count = _counts(session, recall.id)
    summary["evidence_count"] = evidence_count
    summary["replay_count"] = replay_count

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
        "discovery": discovery_summary(session, recall.id),
        "summary": summary,
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


def audit_log(session: Session, recall_id: str) -> list[dict]:
    """Chronological audit trail (directive "Audit panel": newest first). Reads
    every persisted AuditEvent verbatim — nothing invented, nothing collapsed —
    and exposes timestamp, actor, a human action label and the affected object.
    Result is derived from the event name so "no unexplained events" holds."""
    events = session.execute(
        select(AuditEvent)
        .where(AuditEvent.recall_event_id == recall_id)
        .order_by(AuditEvent.created_at.desc())
    ).scalars().all()
    out: list[dict] = []
    for e in events:
        detail = e.detail if isinstance(e.detail, dict) else {}
        obj = None
        if detail.get("asset_id"):
            obj = _node_name(session, str(detail["asset_id"]))
        elif detail.get("recall_id"):
            obj = "Recall"
        ev = e.event
        if ev.endswith(".failed") or ev == "repair.failed":
            result = "failed"
        elif ev.endswith(".rejected") or ev.endswith(".blocked"):
            result = "rejected"
        else:
            result = "ok"
        out.append({
            "at": e.created_at.isoformat() if e.created_at else None,
            "time": _hhmm(e.created_at),
            "actor": e.actor,
            "event": ev,
            "label": _TIMELINE_LABELS.get(ev, ev.replace(".", " ").replace("_", " ").capitalize()),
            "object": obj,
            "result": result,
        })
    return out


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
        "audit": audit_log(session, recall.id),
    }
