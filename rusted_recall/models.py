"""Typed relational domain model (directive section 9).

Constraints enforced here / by the services layer:
* IDs are stable UUID strings.
* Asset versions are immutable (no update path; new rows only).
* Original B2 object keys are never overwritten.
* Recall events reference exact source-of-truth versions.
* Score components are stored, not only a final score.
* Audit events are append-only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --- identity & tenancy (spec sections 25-28) ----------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list[OrganisationMembership]] = relationship(back_populates="user")


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(20), default="trial")  # trial | pro | business
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    memberships: Mapped[list[OrganisationMembership]] = relationship(back_populates="org")
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="org")


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(ForeignKey("organisations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner|admin|member|viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    org: Mapped[Organisation] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class UserSession(Base):
    """Server-side verified session (spec section 27). The opaque token is stored
    only as a hash; the raw token lives solely in the client's secure cookie."""

    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organisations.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    org: Mapped[Organisation | None] = relationship(back_populates="workspaces")
    assets: Mapped[list[Asset]] = relationship(back_populates="workspace")
    source_items: Mapped[list[SourceOfTruthItem]] = relationship(back_populates="workspace")
    recalls: Mapped[list[RecallEvent]] = relationship(back_populates="workspace")


class SourceOfTruthItem(Base):
    __tablename__ = "source_of_truth_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))  # product_package | marketing_claim | ...
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str] = mapped_column(String(100), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="source_items")
    versions: Mapped[list[SourceOfTruthVersion]] = relationship(back_populates="item")


class SourceOfTruthVersion(Base):
    __tablename__ = "source_of_truth_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    item_id: Mapped[str] = mapped_column(ForeignKey("source_of_truth_items.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200), default="")  # e.g. "24-Hour Vitality"
    claim_text: Mapped[str] = mapped_column(Text, default="")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reference_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_phash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    item: Mapped[SourceOfTruthItem] = relationship(back_populates="versions")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    asset_type: Mapped[str] = mapped_column(String(50))  # hero_ad | square_social | ...
    campaign: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    publication_status: Mapped[str] = mapped_column(String(30), default="draft")
    parent_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True, index=True
    )
    # How this asset derives from its parent, when applicable: crop | resize |
    # translate | None. Deterministic derivations (crop/resize) let the Minimal
    # Repair Planner rebuild the child without a generative operation.
    derivation_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="assets")
    versions: Mapped[list[AssetVersion]] = relationship(back_populates="asset")


class AssetVersion(Base):
    """Immutable asset version. Never updated in place; a repair creates a new row."""

    __tablename__ = "asset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    origin: Mapped[str] = mapped_column(String(30), default="uploaded")  # uploaded | repaired
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str] = mapped_column(String(100), default="image/png")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    b2_key: Mapped[str] = mapped_column(String(500))
    preview_b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    analysis_b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manifest_b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    asset: Mapped[Asset] = relationship(back_populates="versions")


class ArtifactObject(Base):
    """Tracks every B2 object the app created so deletes never orphan storage."""

    __tablename__ = "artifact_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    b2_key: Mapped[str] = mapped_column(String(500), unique=True)
    kind: Mapped[str] = mapped_column(String(50))  # original | preview | manifest | report | ...
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    backend: Mapped[str] = mapped_column(String(30), default="local-dev")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DependencyEdge(Base):
    __tablename__ = "dependency_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_node: Mapped[str] = mapped_column(String(80))  # "sot:<id>" or "asset:<id>"
    target_node: Mapped[str] = mapped_column(String(80))
    edge_type: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_type: Mapped[str] = mapped_column(String(50))
    evidence_details: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(80), default="")
    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    recall_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("recall_events.id"), nullable=True
    )
    model_version: Mapped[str] = mapped_column(String(80), default="")
    config_hash: Mapped[str] = mapped_column(String(64), default="")
    edges_created: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RecallEvent(Base):
    __tablename__ = "recall_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_item_id: Mapped[str] = mapped_column(ForeignKey("source_of_truth_items.id"))
    old_version_id: Mapped[str] = mapped_column(ForeignKey("source_of_truth_versions.id"))
    new_version_id: Mapped[str] = mapped_column(ForeignKey("source_of_truth_versions.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    markets: Mapped[list] = mapped_column(JSON, default=list)
    requested_action: Mapped[str] = mapped_column(String(50), default="repair")
    created_by: Mapped[str] = mapped_column(String(120), default="demo-user")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # First-class structured ChangeSet (spec section 10) and the computed
    # Minimal Repair Plan graph (spec section 18), persisted as JSON.
    changeset: Mapped[dict] = mapped_column(JSON, default=dict)
    repair_plan_graph: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    workspace: Mapped[Workspace] = relationship(back_populates="recalls")
    impacts: Mapped[list[RecallImpact]] = relationship(back_populates="recall")


class RecallImpact(Base):
    __tablename__ = "recall_impacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recall_event_id: Mapped[str] = mapped_column(ForeignKey("recall_events.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    classification: Mapped[str] = mapped_column(String(30))
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_components: Mapped[dict] = mapped_column(JSON, default=dict)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    strongest_path: Mapped[dict] = mapped_column(JSON, default=dict)
    recommended_action: Mapped[str] = mapped_column(String(50), default="")
    # Change Propagation Engine outputs (spec sections 15-17).
    propagation_reason: Mapped[str] = mapped_column(Text, default="")
    causal_explanation: Mapped[str] = mapped_column(Text, default="")
    repair_requirement: Mapped[str] = mapped_column(String(40), default="")
    distribution_risk: Mapped[str] = mapped_column(String(20), default="low")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    recall: Mapped[RecallEvent] = relationship(back_populates="impacts")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recall_event_id: Mapped[str] = mapped_column(ForeignKey("recall_events.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30))  # approve | exclude | mark_safe | reclassify
    new_classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(120), default="demo-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RepairPlanRow(Base):
    __tablename__ = "repair_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recall_event_id: Mapped[str] = mapped_column(ForeignKey("recall_events.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    asset_version_id: Mapped[str] = mapped_column(ForeignKey("asset_versions.id"))
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RepairJob(Base):
    __tablename__ = "repair_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recall_event_id: Mapped[str] = mapped_column(ForeignKey("recall_events.id"), index=True)
    repair_plan_id: Mapped[str] = mapped_column(ForeignKey("repair_plans.id"))
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued|running|completed|failed|requires_review
    stage: Mapped[str] = mapped_column(String(50), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, default="")
    result_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repair_job_id: Mapped[str] = mapped_column(ForeignKey("repair_jobs.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    genblaze_pipeline: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    manifest_b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ValidationResultRow(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repair_job_id: Mapped[str] = mapped_column(ForeignKey("repair_jobs.id"), index=True)
    asset_version_id: Mapped[str] = mapped_column(ForeignKey("asset_versions.id"))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[list] = mapped_column(JSON, default=list)
    b2_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Append-only audit log (directive section 9)."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    recall_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("recall_events.id"), nullable=True, index=True
    )
    actor: Mapped[str] = mapped_column(String(120), default="system")
    event: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    kind: Mapped[str] = mapped_column(String(50), default="image")
    model: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageEvent(Base):
    """Metered real actions (spec section 48). One row per billable/metered
    operation, always tied to an organisation + workspace."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str | None] = mapped_column(
        ForeignKey("organisations.id"), nullable=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    event: Mapped[str] = mapped_column(String(60), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
