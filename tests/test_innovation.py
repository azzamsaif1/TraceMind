"""Innovation / generalisation proofs over the UNCHANGED engine
(FINAL DELIVERY §18: target-state inference, causal semantics, global vs local
optimisation, generative necessity, provider independence, blind generalisation,
fixpoint/idempotence).

These exercise the real production engine (services + propagation + planner);
none of them contain company-specific names, IDs, or expected-answer tables.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings, get_settings
from rusted_recall.models import Asset, AssetVersion, RecallImpact, RepairJob
from rusted_recall.planner import (
    METHOD_CONTROLLED_REGENERATION,
    METHOD_DETERMINISTIC_CROP,
    MinimalRepairPlanner,
    PlannerAsset,
)
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.providers.gmicloud import GMICloudProvider
from rusted_recall.storage import get_storage
from tests.support import LocalEditProvider


def _img(color=(30, 120, 60), size=(160, 160)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'r.db'}")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path / "store"))
    get_settings.cache_clear()
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'r.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Planner-level proofs (deterministic, no DB): decisions respond to topology and
# capability, not to a fixed asset_type -> method mapping.
# ---------------------------------------------------------------------------

def test_global_optimum_beats_local_repair():
    """Shared ancestor + deterministic descendants: repair the ancestor once and
    rebuild descendants, instead of independently regenerating each (local)."""
    assets = [
        PlannerAsset(id="root", name="Root"),
        PlannerAsset(id="c1", name="C1", parent_asset_id="root", derivation_method="crop"),
        PlannerAsset(id="c2", name="C2", parent_asset_id="root", derivation_method="resize"),
        PlannerAsset(id="c3", name="C3", parent_asset_id="root", derivation_method="crop"),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    assert plan.naive_generative_operations == 4  # local baseline
    assert plan.generative_operations == 1        # global: repair root once
    assert plan.deterministic_rebuilds == 3
    assert plan.operations_avoided == 3


def test_decision_changes_when_topology_changes():
    """Counterfactual: make the same assets independent (no derivation) and the
    planner's decision flips to per-asset generation — no code change."""
    derived = [
        PlannerAsset(id="root", name="Root"),
        PlannerAsset(id="c1", name="C1", parent_asset_id="root", derivation_method="crop"),
    ]
    independent = [
        PlannerAsset(id="root", name="Root"),
        PlannerAsset(id="c1", name="C1"),  # relationship removed
    ]
    p_derived = MinimalRepairPlanner().plan(derived, requires_generative=True)
    p_indep = MinimalRepairPlanner().plan(independent, requires_generative=True)
    assert p_derived.generative_operations == 1 and p_derived.operations_avoided == 1
    assert p_indep.generative_operations == 2 and p_indep.operations_avoided == 0


def test_generative_necessity_depends_on_change_semantics():
    """Generation is chosen only when the change requires imagery; a pure text
    change is reconciled deterministically with zero generative operations."""
    assets = [PlannerAsset(id="a", name="A")]
    gen = MinimalRepairPlanner().plan(assets, requires_generative=True)
    txt = MinimalRepairPlanner().plan(assets, requires_generative=False)
    assert gen.generative_operations == 1
    assert txt.generative_operations == 0
    assert gen.nodes[0].method == METHOD_CONTROLLED_REGENERATION
    assert txt.nodes[0].method != METHOD_CONTROLLED_REGENERATION


def test_deterministic_child_method_is_rebuild():
    assets = [
        PlannerAsset(id="root", name="Root"),
        PlannerAsset(id="c1", name="C1", parent_asset_id="root", derivation_method="crop"),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    methods = {n.asset_id: n.method for n in plan.nodes}
    assert methods["root"] == METHOD_CONTROLLED_REGENERATION
    assert methods["c1"] == METHOD_DETERMINISTIC_CROP


# ---------------------------------------------------------------------------
# Blind generic-company generalisation (end-to-end through the same services the
# web UI uses). Generic names only; no demo module, no seed script.
# ---------------------------------------------------------------------------

def _build_blind_company(s, storage):
    ws = services.create_workspace(s, "Zephyr Instruments")
    item, old_v = services.register_source_of_truth(
        s, storage, ws, type="product_package", name="Flagship Spec",
        description="approved product truth", label="v1",
        claim_text="Certified Titanium Body", reference_image=_img((200, 40, 40)),
    )
    master, _ = services.ingest_asset(
        s, storage, ws, data=_img((200, 40, 40)), filename="master.png", name="Catalogue Master",
        asset_type="master", description="hero catalogue image",
        declared_source_item_id=item.id, on_image_text="Certified Titanium Body",
    )
    # deterministic crop child of the master
    services.ingest_asset(
        s, storage, ws, data=_img((200, 40, 40), size=(80, 160)), filename="crop.png",
        name="Sidebar Crop", asset_type="derivative", description="cropped from master",
        parent_asset_id=master.id, derivation_method="crop",
    )
    # independent claim-bearing asset
    services.ingest_asset(
        s, storage, ws, data=_img((40, 60, 200)), filename="flyer.png", name="Trade Flyer",
        asset_type="creative", description="independent flyer",
        declared_source_item_id=item.id, on_image_text="Certified Titanium Body",
    )
    # disconnected asset (no relationship, visually unrelated)
    services.ingest_asset(
        s, storage, ws, data=_img((10, 200, 10)), filename="notice.png", name="Break Room Notice",
        asset_type="internal", description="unrelated internal notice",
    )
    new_v = services.add_source_version(
        s, ws, item, label="v2", claim_text="Certified Aerospace Alloy Body",
        storage=storage, reference_image=_img((40, 40, 200)),
    )
    recall = services.create_recall_event(
        s, ws, item=item, old_version=old_v, new_version=new_v, reason="claim update", markets=["US"],
    )
    services.run_impact_analysis(s, ws, recall)
    return ws, recall


def test_blind_company_generalises_without_code_changes(env):
    storage = env
    with db.session_scope() as s:
        ws, recall = _build_blind_company(s, storage)
        impacts = {
            s.get(Asset, i.asset_id).name: i
            for i in s.execute(
                select(RecallImpact).where(RecallImpact.recall_event_id == recall.id)
            ).scalars().all()
        }
        # Disconnected, visually-unrelated asset stays safe (not blindly affected).
        assert impacts["Break Room Notice"].classification == "safe"
        # The declared, claim-bearing master is affected and explainable.
        master = impacts["Catalogue Master"]
        assert master.classification in ("directly_affected", "probably_affected")
        assert master.causal_explanation and master.strongest_path
        # A repair plan DAG was inferred (not supplied by the user).
        assert recall.repair_plan_graph
        assert recall.repair_plan_graph["naive_generative_operations"] >= \
            recall.repair_plan_graph["generative_operations"]


def test_engine_reasons_without_any_provider(env):
    """Provider-independence (spec §1 hard invariant): the blind company's change
    is deterministic (text claim + a crop derivative), so with NO generative
    provider configured the repairs still complete NATIVELY — provider disabled
    never removes native intelligence, and native work never calls a provider."""
    storage = env
    with db.session_scope() as s:
        ws, recall = _build_blind_company(s, storage)
        # Plan is entirely deterministic: zero generative operations.
        assert recall.repair_plan_graph
        assert recall.repair_plan_graph["generative_operations"] == 0

        # An UNCONFIGURED provider must never even be touched for a native plan.
        unconfigured = GMICloudProvider(Settings(gmicloud_api_key=None))
        assert unconfigured.configured is False
        jobs = services.approve_and_repair(
            s, storage, ws, recall, GenblazePipeline(primary=unconfigured),
            provider_name="gmicloud", model="seedream-5.0-pro", max_repairs=3,
        )
        # Native repairs complete despite no provider; recall reaches COMPLETED.
        assert jobs and all(j.status == "completed" for j in jobs)
        assert recall.status == recall_fsm.COMPLETED
        # Real repaired versions were produced locally.
        repaired = s.execute(
            select(AssetVersion).where(AssetVersion.origin == "repaired")
        ).scalars().all()
        assert repaired


def test_reconciliation_is_idempotent_at_fixpoint(env):
    """After a successful reconciliation, re-running produces NO new versions or
    jobs (terminal no-op) — execution never repeats already-reconciled work."""
    storage = env
    with db.session_scope() as s:
        ws, recall = _build_blind_company(s, storage)
        pipeline = GenblazePipeline(primary=LocalEditProvider())
        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )

        def counts():
            v = len(s.execute(select(AssetVersion).where(AssetVersion.origin == "repaired")).scalars().all())
            j = len(s.execute(select(RepairJob)).scalars().all())
            return v, j

        before = counts()
        services.approve_and_repair(
            s, storage, ws, recall, pipeline,
            provider_name="test-local-edit", model="test/local-edit-1", max_repairs=3,
        )
        assert counts() == before
