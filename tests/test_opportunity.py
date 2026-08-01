"""Verified Opportunity tests (spec section 3).

An opportunity must derive from the *verified* Recall state transition and pass
    candidate → causal → constraint → feasibility → counterfactual → VERIFIED
before it is surfaced. Execution runs through the SAME real engine, stays native
when native, and reports partial/blocked truthfully. NO EVIDENCE → NO CLAIM.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services
from rusted_recall import opportunity as opp
from rusted_recall import recall as recall_fsm
from rusted_recall.config import Settings
from rusted_recall.hashing import sha256_bytes
from rusted_recall.models import Asset, AssetVersion, GenerationRun, Opportunity
from rusted_recall.providers.base import GenerationRequest, GenerationResult
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.storage import get_storage


def _img(color=(200, 40, 40), size=(160, 160)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class ExplodingProvider:
    name = "exploding"
    model = "should-never-run"
    calls = 0

    @property
    def configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        ExplodingProvider.calls += 1
        raise AssertionError("provider invoked for a native opportunity")

    def health_check(self) -> bool:
        return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'o.db'}")
    db.reset_engine()
    db.create_all()
    settings = Settings(
        app_env="development", storage_backend="local",
        local_storage_dir=str(tmp_path / "store"),
        database_url=f"sqlite:///{tmp_path/'o.db'}",
    )
    yield get_storage(settings)
    db.reset_engine()


def _repair_master_leave_crop(s, storage):
    """Repair ONLY the master (claim change), leaving its crop derivative stale.
    That leftover, now-reconcilable-from-the-repaired-parent crop is the machine
    -grounded opportunity created by the verified transition."""
    ws = services.create_workspace(s, "Opp Co")
    item, old_v = services.register_source_of_truth(
        s, storage, ws, type="product_package", name="Label", description="truth",
        label="v1", claim_text="24-Hour Vitality", reference_image=_img(),
    )
    master, _ = services.ingest_asset(
        s, storage, ws, data=_img(), filename="master.png", name="Master",
        asset_type="master", description="hero", declared_source_item_id=item.id,
        on_image_text="24-Hour Vitality",
    )
    services.ingest_asset(
        s, storage, ws, data=_img(size=(80, 160)), filename="crop.png",
        name="Crop", asset_type="derivative", description="cropped from master",
        parent_asset_id=master.id, derivation_method="crop",
    )
    new_v = services.add_source_version(
        s, ws, item, label="v2", claim_text="Daily Botanical Blend",
        storage=storage, reference_image=_img(),
    )
    recall = services.create_recall_event(
        s, ws, item=item, old_version=old_v, new_version=new_v,
        reason="claim update", markets=["US"],
    )
    services.run_impact_analysis(s, ws, recall)
    # Approve ONLY the master, so the crop stays on the old state.
    services.approve_and_repair(
        s, storage, ws, recall, GenblazePipeline(primary=ExplodingProvider()),
        provider_name="native", model="deterministic", asset_ids=[master.id],
        max_repairs=5,
    )
    return ws, recall, master


def test_discovers_verified_native_opportunity(env):
    storage = env
    with db.session_scope() as s:
        ws, recall, master = _repair_master_leave_crop(s, storage)
        assert recall.status in (recall_fsm.COMPLETED, recall_fsm.PARTIALLY_COMPLETED)

        opps = services.discover_opportunities(s, storage, ws, recall, provider_usable=False)
        assert len(opps) == 1
        o = opps[0]
        assert o.status == opp.STATUS_VERIFIED
        assert o.kind == opp.KIND_RECONCILE_DERIVATIVE
        assert o.native_operations == 1
        assert o.generative_operations == 0
        assert o.feasibility_state == "executable"
        # Causal + counterfactual evidence is persisted and machine-grounded.
        ev = o.evidence
        assert ev["causal_path"][0]["role"] == "trigger"
        assert ev["counterfactual"]["already_valid_before"] is False


def test_execute_native_opportunity_produces_verified_artifact(env):
    storage = env
    ExplodingProvider.calls = 0
    with db.session_scope() as s:
        ws, recall, master = _repair_master_leave_crop(s, storage)
        o = services.discover_opportunities(s, storage, ws, recall, provider_usable=False)[0]

        services.execute_opportunity(
            s, storage, ws, o, GenblazePipeline(primary=ExplodingProvider()),
            provider_name="native", model="deterministic",
        )
        assert ExplodingProvider.calls == 0  # native stays native
        assert o.status == opp.STATUS_EXECUTED
        assert o.executed_operations == 1
        assert o.blocked_operations == 0

        crop = s.execute(
            select(Asset).where(Asset.workspace_id == ws.id, Asset.name == "Crop")
        ).scalars().first()
        rebuilt = s.execute(
            select(AssetVersion).where(
                AssetVersion.asset_id == crop.id, AssetVersion.origin == "repaired"
            )
        ).scalars().first()
        assert rebuilt is not None
        assert (rebuilt.width, rebuilt.height) == (80, 160)
        # Real B2 read-back + hash proof; lineage preserved.
        assert sha256_bytes(storage.get_bytes(rebuilt.b2_key)) == rebuilt.sha256
        assert rebuilt.parent_version_id is not None
        # No generative run for a native opportunity execution.
        runs = s.execute(select(GenerationRun)).scalars().all()
        assert runs == []


def test_rediscovery_is_idempotent_noop(env):
    storage = env
    with db.session_scope() as s:
        ws, recall, master = _repair_master_leave_crop(s, storage)
        first = services.discover_opportunities(s, storage, ws, recall, provider_usable=False)
        second = services.discover_opportunities(s, storage, ws, recall, provider_usable=False)
        assert {o.id for o in first} == {o.id for o in second}
        total = s.execute(
            select(Opportunity).where(Opportunity.recall_event_id == recall.id)
        ).scalars().all()
        assert len(total) == len(first)  # no duplicates on re-run


def test_execute_refuses_blocked_opportunity(env):
    storage = env
    with db.session_scope() as s:
        ws, recall, master = _repair_master_leave_crop(s, storage)
        o = services.discover_opportunities(s, storage, ws, recall, provider_usable=False)[0]
        o.status = opp.STATUS_BLOCKED
        s.flush()
        with pytest.raises(ValueError):
            services.execute_opportunity(
                s, storage, ws, o, GenblazePipeline(primary=ExplodingProvider()),
            )


# --- Pure lifecycle logic (no DB): causal / counterfactual / feasibility ---

def _candidate(**kw):
    base = dict(
        asset_id="c1", name="Crop", derivation_method="crop",
        parent_asset_id="p1", parent_repaired=True,
        parent_repaired_version_id="v-repaired", parent_name="Master",
        already_repaired=False, already_reconciled=False, width=80, height=160,
    )
    base.update(kw)
    return opp.CandidateAsset(**base)


def test_causal_rejects_without_repaired_parent():
    a = opp.assess_reconcile_candidate(
        _candidate(parent_repaired=False, parent_repaired_version_id=None),
        trigger={}, provider_usable=True,
    )
    assert a.status == opp.STATUS_REJECTED
    assert a.evidence["rejected_reason"] == "no_causal_evidence"


def test_counterfactual_rejects_already_valid_before():
    a = opp.assess_reconcile_candidate(
        _candidate(already_reconciled=True), trigger={}, provider_usable=True,
    )
    assert a.status == opp.STATUS_REJECTED
    assert a.evidence["rejected_reason"] == "valid_before_change"


def test_generative_candidate_blocked_without_usable_provider():
    a = opp.assess_reconcile_candidate(
        _candidate(derivation_method=None), trigger={}, provider_usable=False,
    )
    assert a.status == opp.STATUS_BLOCKED
    assert a.blocked_operations == 1
    assert a.feasibility_state == "blocked"


def test_generative_candidate_verified_with_usable_provider():
    a = opp.assess_reconcile_candidate(
        _candidate(derivation_method=None), trigger={}, provider_usable=True,
    )
    assert a.status == opp.STATUS_VERIFIED
    assert a.generative_operations == 1
    assert a.blocked_operations == 0
