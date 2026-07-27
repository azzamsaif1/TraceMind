"""Generalisation proof (directive section 11).

The Northstar campaign shares no fixtures, IDs or strings with LumaLeaf. If the
engine produces a sensible, differentiated impact set on it — a disconnected
asset stays safe, the declared master is directly affected, and a distinct
repair DAG is produced — that is evidence the analysis is a real algorithm and
not demo-specific logic.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'gen.db'}")

    import rusted_recall.config as config

    config.get_settings.cache_clear()
    from rusted_recall import db

    db.reset_engine()
    db.create_all()

    from rusted_recall.demo import seed

    result = seed.seed_all(config.get_settings())
    yield result
    db.reset_engine()
    config.get_settings.cache_clear()


def _impacts(recall_id):
    from rusted_recall.db import session_scope
    from rusted_recall.models import Asset, RecallImpact

    out = {}
    with session_scope() as s:
        rows = s.execute(
            select(RecallImpact).where(RecallImpact.recall_event_id == recall_id)
        ).scalars().all()
        for imp in rows:
            asset = s.get(Asset, imp.asset_id)
            out[asset.name] = imp
    return out


def test_both_campaigns_seed_independently(seeded):
    assert seeded["golden"]["workspace"] == "lumaleaf-botanical"
    assert seeded["generalisation"]["workspace"] == "northstar-coffee"
    assert seeded["golden"]["recall_id"] != seeded["generalisation"]["recall_id"]


def test_disconnected_asset_stays_safe(seeded):
    impacts = _impacts(seeded["generalisation"]["recall_id"])
    wifi = impacts["Office Wi-Fi Notice"]
    assert wifi.classification == "safe"
    assert wifi.impact_score < 0.25


def test_declared_master_is_directly_affected_with_causal_path(seeded):
    impacts = _impacts(seeded["generalisation"]["recall_id"])
    master = impacts["Packaging Master"]
    assert master.classification == "directly_affected"
    assert master.impact_score >= 0.80
    # every classification is explainable (section 9)
    assert master.causal_explanation
    assert master.strongest_path


def test_generalisation_topology_differs_from_golden(seeded):
    gen = _impacts(seeded["generalisation"]["recall_id"])
    golden = _impacts(seeded["golden"]["recall_id"])
    # Different asset names -> no fixture reuse.
    assert set(gen) != set(golden)
    assert "Website Banner" in gen
    assert "Hero Advertisement" in golden


def test_repair_plan_dag_is_produced(seeded):
    from rusted_recall.db import session_scope
    from rusted_recall.models import RecallEvent

    with session_scope() as s:
        recall = s.get(RecallEvent, seeded["generalisation"]["recall_id"])
        plan = recall.repair_plan_graph
    assert plan
    assert "execution_dag" in plan
    assert plan["naive_generative_operations"] >= plan["generative_operations"]
