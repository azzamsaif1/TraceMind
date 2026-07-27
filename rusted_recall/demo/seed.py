"""Demo seeding orchestration (directive sections 6, 11, 21).

Seeds two independent campaigns through the production services:

* the **golden production recall** (LumaLeaf), preserved for judges as reliable
  proof even if a provider is slow during evaluation;
* the **generalisation recall** (Northstar Coffee), a second campaign with a
  different dependency topology that shares zero fixtures with LumaLeaf and
  proves the engine is not hard-coded to the demo.

``ensure_seeded`` is idempotent so ``Run Live Recall`` can call it on every
request without duplicating data.
"""
from __future__ import annotations

from sqlalchemy import select

from rusted_recall.config import Settings, get_settings
from rusted_recall.db import session_scope
from rusted_recall.demo import lumaleaf, northstar
from rusted_recall.models import RecallEvent, Workspace


def seed_all(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    golden = lumaleaf.seed(settings)
    generalisation = northstar.seed(settings)
    return {"golden": golden, "generalisation": generalisation}


def ensure_seeded(settings: Settings | None = None) -> dict:
    """Seed both campaigns if missing; safe to call repeatedly."""
    return seed_all(settings)


def _latest_recall_for_slug(session, slug: str) -> RecallEvent | None:
    ws = session.execute(
        select(Workspace).where(Workspace.slug == slug)
    ).scalars().first()
    if ws is None:
        return None
    return session.execute(
        select(RecallEvent)
        .where(RecallEvent.workspace_id == ws.id)
        .order_by(RecallEvent.created_at.desc())
    ).scalars().first()


def golden_recall_id(settings: Settings | None = None) -> str | None:
    with session_scope() as session:
        recall = _latest_recall_for_slug(session, lumaleaf.SLUG)
        return recall.id if recall else None


def generalisation_recall_id(settings: Settings | None = None) -> str | None:
    with session_scope() as session:
        recall = _latest_recall_for_slug(session, northstar.SLUG)
        return recall.id if recall else None


if __name__ == "__main__":
    import json

    print(json.dumps(seed_all(), indent=2))
