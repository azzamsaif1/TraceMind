"""Self-guiding contextual next-step control (spec section 4 / "Help").

This is NOT a chatbot and NOT documentation. It derives the single most useful
next action directly from the *actual* persisted workspace state, so a first-time
company always knows what to do next. The transitions mirror the product journey:

    no workspace              → sign up / onboard
    no Source of Truth        → register one
    truth but no asset        → register the first asset
    asset but no dependency   → declare the relationship / evidence
    truth + assets, no recall → create the first Recall
    recall awaiting review    → review and approve
    approved / repairing      → run / watch repairs
    partially completed       → inspect completed / failed / blocked work
    verified recall           → discover Verified Opportunities
    opportunities discovered  → execute an opportunity
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rusted_recall.models import (
    Asset,
    DependencyEdge,
    Opportunity,
    RecallEvent,
    SourceOfTruthItem,
    Workspace,
)


@dataclass(frozen=True)
class Guide:
    state: str
    title: str
    message: str
    cta_label: str
    cta_href: str

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "title": self.title,
            "message": self.message,
            "cta_label": self.cta_label,
            "cta_href": self.cta_href,
        }


def _count(session: Session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for k, v in filters.items():
        stmt = stmt.where(getattr(model, k) == v)
    return int(session.execute(stmt).scalar_one())


def next_step(session: Session, workspace: Workspace | None, *, can_edit: bool) -> Guide:
    """Return the single most relevant next action for the current viewer."""
    if workspace is None or not can_edit:
        return Guide(
            state="onboard",
            title="Welcome to Rusted Recall",
            message=(
                "Create your company workspace to manage your Sources of Truth and "
                "the media that must stay consistent with them."
            ),
            cta_label="Start onboarding",
            cta_href="/onboarding",
        )

    wid = workspace.id
    sources = _count(session, SourceOfTruthItem, workspace_id=wid)
    if sources == 0:
        return Guide(
            state="no_source_of_truth",
            title="Register your first Source of Truth",
            message=(
                "A Source of Truth is the approved reference — a logo, claim or "
                "likeness — that your media must follow. Register one to begin."
            ),
            cta_label="Register Source of Truth",
            cta_href="/sources",
        )

    assets = _count(session, Asset, workspace_id=wid)
    if assets == 0:
        return Guide(
            state="no_asset",
            title="Register your first asset",
            message=(
                "Add a media asset (an ad, social image, packaging shot …) that "
                "depends on a Source of Truth so Rusted can track it."
            ),
            cta_label="Register Asset",
            cta_href="/assets",
        )

    edges = _count(session, DependencyEdge, workspace_id=wid)
    if edges == 0:
        return Guide(
            state="no_dependency",
            title="Declare a dependency",
            message=(
                "Tell Rusted how an asset relates to a Source of Truth (or to a "
                "parent asset). These relationships are what impact propagates along."
            ),
            cta_label="Declare Dependency",
            cta_href="/assets",
        )

    recalls = list(session.execute(
        select(RecallEvent).where(RecallEvent.workspace_id == wid)
        .order_by(RecallEvent.created_at.desc())
    ).scalars().all())
    if not recalls:
        return Guide(
            state="ready_for_recall",
            title="Create your first Recall",
            message=(
                "Your truth and assets are connected. When a Source of Truth "
                "changes, create a Recall to compute the causal impact and plan repairs."
            ),
            cta_label="Create Recall",
            cta_href="/recalls/new",
        )

    latest = recalls[0]
    href = f"/recalls/{latest.id}"
    status = latest.status
    if status in ("draft", "analysing", "ready_for_review"):
        return Guide(
            state="awaiting_review",
            title="Review the impact and approve",
            message=(
                "Rusted classified each asset (directly / probably affected, needs "
                "review, safe) with causal evidence. Review the queue, then approve "
                "to plan the minimal repair."
            ),
            cta_label="Open recall",
            cta_href=href,
        )
    if status in ("approved", "repairing"):
        return Guide(
            state="repairing",
            title="Repairs are running",
            message=(
                "Deterministic repairs execute natively (no provider); generative "
                "repairs route through Genblaze only when required. Watch progress "
                "and verification on the recall."
            ),
            cta_label="Watch progress",
            cta_href=href,
        )
    if status == "partially_completed":
        return Guide(
            state="partially_completed",
            title="Some work is unfinished",
            message=(
                "Completed repairs produced verified versions; remaining items are "
                "failed or blocked (e.g. generation needs a usable provider). Inspect "
                "them and retry the failed operations."
            ),
            cta_label="Inspect & retry",
            cta_href=href,
        )
    if status == "completed":
        opps = _count(session, Opportunity, recall_event_id=latest.id)
        if opps == 0:
            return Guide(
                state="verified",
                title="Discover Verified Opportunities",
                message=(
                    "This Recall is verified. Rusted can now derive executable "
                    "opportunities created specifically by this state change — each "
                    "backed by causal, counterfactual and feasibility proof."
                ),
                cta_label="Explore opportunities",
                cta_href=href + "#opportunities",
            )
        return Guide(
            state="opportunities",
            title="Execute a Verified Opportunity",
            message=(
                "Verified Opportunities are ready. Each explains why it exists and "
                "what Execute will actually do — real operations with stored, "
                "verified artifacts."
            ),
            cta_label="Review & execute",
            cta_href=href + "#opportunities",
        )
    return Guide(
        state="idle",
        title="Start a new Recall",
        message="Your latest Recall is closed. Create a new one when a Source of Truth changes.",
        cta_label="Create Recall",
        cta_href="/recalls/new",
    )
