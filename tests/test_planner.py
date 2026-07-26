from rusted_recall.planner import (
    METHOD_CONTROLLED_REGENERATION,
    METHOD_DETERMINISTIC_CROP,
    METHOD_MANUAL_REVIEW,
    MinimalRepairPlanner,
    PlannerAsset,
)


def test_deterministic_children_are_rebuilt_not_regenerated():
    # master (generative) + two crops derived from it (deterministic rebuilds).
    assets = [
        PlannerAsset(id="master", name="Master"),
        PlannerAsset(
            id="hero", name="Hero", parent_asset_id="master", derivation_method="crop"
        ),
        PlannerAsset(
            id="email", name="Email", parent_asset_id="master", derivation_method="resize"
        ),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    assert plan.naive_generative_operations == 3
    assert plan.generative_operations == 1
    assert plan.deterministic_rebuilds == 2
    assert plan.operations_avoided == 2

    methods = {n.asset_id: n.method for n in plan.nodes}
    assert methods["master"] == METHOD_CONTROLLED_REGENERATION
    assert methods["hero"] == METHOD_DETERMINISTIC_CROP


def test_execution_dag_links_children_to_parent():
    assets = [
        PlannerAsset(id="master", name="Master"),
        PlannerAsset(id="hero", name="Hero", parent_asset_id="master", derivation_method="crop"),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    dag = plan.execution_dag()
    assert dag["master"] == ["hero"]


def test_independent_assets_all_need_generative():
    assets = [
        PlannerAsset(id="a", name="A"),
        PlannerAsset(id="b", name="B"),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    assert plan.generative_operations == 2
    assert plan.operations_avoided == 0


def test_child_of_non_repaired_parent_is_generative():
    # parent not in the repair set -> child cannot be deterministically rebuilt.
    assets = [
        PlannerAsset(id="hero", name="Hero", parent_asset_id="missing", derivation_method="crop"),
    ]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    assert plan.generative_operations == 1
    assert plan.deterministic_rebuilds == 0


def test_needs_review_asset_is_manual():
    assets = [PlannerAsset(id="x", name="X", needs_review=True)]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=True)
    assert plan.manual_reviews == 1
    assert plan.nodes[0].method == METHOD_MANUAL_REVIEW
    # manual-review items are excluded from the naive baseline.
    assert plan.naive_generative_operations == 0


def test_pure_text_change_uses_deterministic_overlay():
    assets = [PlannerAsset(id="a", name="A")]
    plan = MinimalRepairPlanner().plan(assets, requires_generative=False)
    assert plan.generative_operations == 0
    assert plan.deterministic_rebuilds == 1
