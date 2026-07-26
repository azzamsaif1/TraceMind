from rusted_recall import evidence as ev
from rusted_recall.changeset import (
    OP_REPLACE_TEXT,
    OP_REPLACE_VISUAL,
    ChangeOperation,
    ChangeSet,
)
from rusted_recall.graph import DependencyGraph
from rusted_recall.propagation import (
    AssetInput,
    ChangePropagationEngine,
    EdgeInput,
    components_from_edges,
)

SRC = "sot:s1"


def _graph(edges):
    g = DependencyGraph()
    for s, t, ty, c in edges:
        g.add_edge(s, t, ty, c)
    return g


def test_text_change_does_not_propagate_through_visual_only_edge():
    # asset a1 only connected to source via a visual-similarity edge.
    graph = _graph([(SRC, "asset:a1", ev.EDGE_VISUAL, 0.9)])
    cs = ChangeSet(
        entity_type="package",
        previous_version="v1",
        new_version="v2",
        operations=[ChangeOperation(type=OP_REPLACE_TEXT, old="a", new="b")],
    )
    engine = ChangePropagationEngine(cs)
    result = engine.compute(
        source_node=SRC,
        graph=graph,
        assets=[AssetInput(id="a1", name="A1")],
        edges_by_target={"asset:a1": [EdgeInput(ev.EDGE_VISUAL, 0.9)]},
    )
    item = result.items[0]
    # visual-only evidence is filtered out for a pure text change -> safe.
    assert item.classification == "safe"


def test_visual_change_propagates_through_visual_edge():
    graph = _graph([(SRC, "asset:a1", ev.EDGE_PHASH_DERIVATIVE, 0.95)])
    cs = ChangeSet(
        entity_type="package",
        previous_version="v1",
        new_version="v2",
        operations=[ChangeOperation(type=OP_REPLACE_VISUAL, field="artwork")],
    )
    engine = ChangePropagationEngine(cs)
    result = engine.compute(
        source_node=SRC,
        graph=graph,
        assets=[AssetInput(id="a1", name="A1", publication_status="published")],
        edges_by_target={"asset:a1": [EdgeInput(ev.EDGE_PHASH_DERIVATIVE, 0.95)]},
        node_labels={SRC: "Source", "asset:a1": "A1"},
    )
    item = result.items[0]
    assert item.classification in ("directly_affected", "probably_affected", "needs_review")
    assert item.strongest_path["edges"]
    assert "A1" in item.causal_explanation


def test_explicit_dependency_always_propagates():
    graph = _graph([(SRC, "asset:a1", ev.EDGE_EXPLICIT, 0.95)])
    cs = ChangeSet(
        entity_type="package",
        previous_version="v1",
        new_version="v2",
        operations=[ChangeOperation(type=OP_REPLACE_TEXT, old="a", new="b")],
    )
    engine = ChangePropagationEngine(cs)
    result = engine.compute(
        source_node=SRC,
        graph=graph,
        assets=[AssetInput(id="a1", name="A1")],
        edges_by_target={
            "asset:a1": [EdgeInput(ev.EDGE_EXPLICIT, 0.95, human_confirmed=True)]
        },
    )
    item = result.items[0]
    assert item.confirmed_dependency
    assert item.classification == "directly_affected"


def test_cycle_safe_and_depth_capped():
    graph = _graph(
        [
            (SRC, "asset:a1", ev.EDGE_EXPLICIT, 0.9),
            ("asset:a1", "asset:a2", ev.EDGE_PARENT_CHILD, 0.9),
            ("asset:a2", "asset:a1", ev.EDGE_PARENT_CHILD, 0.9),  # cycle
        ]
    )
    cs = ChangeSet(
        entity_type="package",
        previous_version="v1",
        new_version="v2",
        operations=[ChangeOperation(type=OP_REPLACE_VISUAL, field="artwork")],
    )
    engine = ChangePropagationEngine(cs)
    result = engine.compute(
        source_node=SRC,
        graph=graph,
        assets=[AssetInput(id="a1", name="A1"), AssetInput(id="a2", name="A2")],
        edges_by_target={
            "asset:a1": [EdgeInput(ev.EDGE_EXPLICIT, 0.9)],
            "asset:a2": [EdgeInput(ev.EDGE_PARENT_CHILD, 0.9)],
        },
    )
    # Both reachable, no infinite loop.
    assert {i.asset_id for i in result.items} == {"a1", "a2"}


def test_components_from_edges_aggregates_max():
    comp, confirmed, conflicting = components_from_edges(
        [
            EdgeInput(ev.EDGE_VISUAL, 0.4),
            EdgeInput(ev.EDGE_VISUAL, 0.8),
            EdgeInput(ev.EDGE_OCR_TEXT, 0.7),
        ]
    )
    assert comp.visual_evidence == 0.8
    assert comp.text_evidence == 0.7
    assert not confirmed


def test_unreachable_asset_with_no_evidence_is_safe():
    graph = _graph([(SRC, "asset:a1", ev.EDGE_EXPLICIT, 0.9)])
    engine = ChangePropagationEngine(None)
    result = engine.compute(
        source_node=SRC,
        graph=graph,
        assets=[AssetInput(id="z", name="Z")],
        edges_by_target={},
    )
    assert result.items[0].classification == "safe"
