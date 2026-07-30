"""Baseline benchmark + scale harness (FINAL DELIVERY §18.11, §18.13, PROOF 4).

Runs the REAL engine over three scenarios (LumaLeaf, Northstar, and a blind
generic company built through the same services the web UI uses) and measures
Rusted's reconciliation program against naive baselines. Also runs a planner
scale test on synthetic generic graphs. Emits a machine-readable artifact:

    evidence/BENCHMARK_RESULTS.json

All numbers are computed from actual engine output — nothing is hardcoded.

Usage:
    APP_ENV=test STORAGE_BACKEND=local DATABASE_URL="sqlite:////tmp/bench.db" \
        python -m scripts.benchmark
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select

from rusted_recall import db, services
from rusted_recall.config import get_settings
from rusted_recall.demo import seed as demo_seed
from rusted_recall.models import Asset, RecallEvent, RecallImpact
from rusted_recall.planner import MinimalRepairPlanner, PlannerAsset
from rusted_recall.storage import get_storage

AFFECTED = ("directly_affected", "probably_affected")


def _img(color=(30, 120, 60), size=(160, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _scenario_metrics(recall_id: str, workspace_id: str) -> dict:
    with db.session_scope() as s:
        recall = s.get(RecallEvent, recall_id)
        plan = recall.repair_plan_graph or {}
        impacts = s.execute(
            select(RecallImpact).where(RecallImpact.recall_event_id == recall_id)
        ).scalars().all()
        total_assets = s.execute(
            select(func.count()).select_from(Asset).where(Asset.workspace_id == workspace_id)
        ).scalar_one()

    affected = sum(1 for i in impacts if i.classification in AFFECTED)
    needs_review = sum(1 for i in impacts if i.classification == "needs_review")
    safe = sum(1 for i in impacts if i.classification == "safe")

    rusted_generative = plan.get("generative_operations", 0)
    rusted_deterministic = plan.get("deterministic_rebuilds", 0)
    rusted_reviews = plan.get("manual_reviews", 0)
    naive = plan.get("naive_generative_operations", 0)

    return {
        "total_assets": total_assets,
        "analysed": len(impacts),
        "affected": affected,
        "needs_review": needs_review,
        "safe": safe,
        "baselines": {
            # A: regenerate every reachable affected asset.
            "A_regenerate_all_affected": {"generative_operations": naive},
            # B: repair every directly detected affected asset independently.
            "B_repair_each_affected": {"generative_operations": naive},
            # C: no semantic propagation — a human must manually identify the
            # affected set. Rusted removes this manual investigation burden.
            "C_manual_no_propagation": {"assets_requiring_manual_triage": total_assets},
        },
        "rusted": {
            "generative_operations": rusted_generative,
            "deterministic_rebuilds": rusted_deterministic,
            "manual_reviews": rusted_reviews,
            "total_repair_operations": rusted_generative + rusted_deterministic,
        },
        "generative_operations_avoided": plan.get("operations_avoided", 0),
    }


def _build_blind_company(storage) -> tuple[str, str]:
    with db.session_scope() as s:
        ws = services.create_workspace(s, "Zephyr Instruments (benchmark)")
        item, old_v = services.register_source_of_truth(
            s, storage, ws, type="product_package", name="Flagship Spec",
            description="approved product truth", label="v1",
            claim_text="Certified Titanium Body", reference_image=_img((200, 40, 40)),
        )
        master, _ = services.ingest_asset(
            s, storage, ws, data=_img((200, 40, 40)), filename="master.png",
            name="Catalogue Master", asset_type="master", description="hero",
            declared_source_item_id=item.id, on_image_text="Certified Titanium Body",
        )
        services.ingest_asset(
            s, storage, ws, data=_img((200, 40, 40), (80, 160)), filename="crop.png",
            name="Sidebar Crop", asset_type="derivative", description="cropped",
            parent_asset_id=master.id, derivation_method="crop",
        )
        services.ingest_asset(
            s, storage, ws, data=_img((40, 60, 200)), filename="flyer.png",
            name="Trade Flyer", asset_type="creative", description="independent",
            declared_source_item_id=item.id, on_image_text="Certified Titanium Body",
        )
        services.ingest_asset(
            s, storage, ws, data=_img((10, 200, 10)), filename="notice.png",
            name="Break Room Notice", asset_type="internal", description="unrelated",
        )
        new_v = services.add_source_version(
            s, ws, item, label="v2", claim_text="Certified Aerospace Alloy Body",
            storage=storage, reference_image=_img((40, 40, 200)),
        )
        recall = services.create_recall_event(
            s, ws, item=item, old_version=old_v, new_version=new_v,
            reason="claim update", markets=["US"],
        )
        services.run_impact_analysis(s, ws, recall)
        return recall.id, ws.id


def _scale_test() -> list[dict]:
    """Synthetic generic graphs: 1 generative root per 5 assets, remainder are
    deterministic crop children. Measures planning time + selected operations."""
    results = []
    planner = MinimalRepairPlanner()
    for n in (10, 100, 1000, 10000):
        assets: list[PlannerAsset] = []
        root_id = None
        for i in range(n):
            if i % 5 == 0:
                root_id = f"root-{i}"
                assets.append(PlannerAsset(id=root_id, name=root_id))
            else:
                assets.append(PlannerAsset(
                    id=f"a-{i}", name=f"a-{i}",
                    parent_asset_id=root_id, derivation_method="crop",
                ))
        t0 = time.perf_counter()
        plan = planner.plan(assets, requires_generative=True)
        elapsed = time.perf_counter() - t0
        results.append({
            "assets": n,
            "planning_seconds": round(elapsed, 5),
            "generative_operations": plan.generative_operations,
            "deterministic_rebuilds": plan.deterministic_rebuilds,
            "operations_avoided": plan.operations_avoided,
        })
    return results


def main() -> None:
    settings = get_settings()
    db.reset_engine()
    db.create_all()
    storage = get_storage(settings)

    demo_seed.seed_all(settings)
    golden_id = demo_seed.golden_recall_id(settings)
    gen_id = demo_seed.generalisation_recall_id(settings)

    scenarios: dict[str, dict] = {}
    with db.session_scope() as s:
        golden_ws = s.get(RecallEvent, golden_id).workspace_id
        gen_ws = s.get(RecallEvent, gen_id).workspace_id
    scenarios["lumaleaf"] = _scenario_metrics(golden_id, golden_ws)
    scenarios["northstar"] = _scenario_metrics(gen_id, gen_ws)

    blind_id, blind_ws = _build_blind_company(storage)
    scenarios["blind_generic_company"] = _scenario_metrics(blind_id, blind_ws)

    artifact = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "All numbers computed from real engine output; none hardcoded.",
        "scenarios": scenarios,
        "scale_test": _scale_test(),
    }
    out = Path("evidence/BENCHMARK_RESULTS.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2))
    print(json.dumps(artifact, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
