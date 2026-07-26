from rusted_recall import evidence as ev
from rusted_recall.changeset import (
    OP_CLAIM_WITHDRAWAL,
    OP_REPLACE_TEXT,
    OP_REPLACE_VISUAL,
    ChangeOperation,
    ChangeSet,
    propose_changeset,
)


def test_operation_validates_type():
    try:
        ChangeOperation(type="not_a_real_type")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown operation type")


def test_replace_text_propagates_through_text_edges_not_visual():
    op = ChangeOperation(type=OP_REPLACE_TEXT, old="a", new="b")
    assert op.propagates_through(ev.EDGE_OCR_TEXT)
    assert op.propagates_through(ev.EDGE_SEMANTIC)
    assert not op.propagates_through(ev.EDGE_VISUAL)
    assert not op.requires_generative_repair


def test_replace_visual_requires_generative_and_visual_edges():
    op = ChangeOperation(type=OP_REPLACE_VISUAL, field="artwork")
    assert op.requires_generative_repair
    assert op.propagates_through(ev.EDGE_VISUAL)
    assert op.propagates_through(ev.EDGE_PHASH_DERIVATIVE)


def test_changeset_serialization_roundtrip():
    cs = ChangeSet(
        entity_type="product_package",
        previous_version="v1",
        new_version="v2",
        operations=[
            ChangeOperation(type=OP_REPLACE_TEXT, field="front_claim", old="old", new="new"),
            ChangeOperation(type=OP_REPLACE_VISUAL, field="package_artwork", inferred=True),
        ],
    )
    restored = ChangeSet.from_dict(cs.as_dict())
    assert restored.entity_type == "product_package"
    assert len(restored.operations) == 2
    assert restored.requires_generative_repair
    assert ev.EDGE_OCR_TEXT in restored.propagating_edge_types()


def test_propose_changeset_detects_text_replacement():
    cs = propose_changeset(
        entity_type="product_package",
        old_version_id="v1",
        new_version_id="v2",
        old_label="LumaLeaf",
        new_label="LumaLeaf",
        old_claim="24-Hour Vitality",
        new_claim="Daily Botanical Blend",
    )
    assert any(op.type == OP_REPLACE_TEXT for op in cs.operations)
    op = next(op for op in cs.operations if op.type == OP_REPLACE_TEXT)
    assert op.confidence == 1.0 and not op.inferred


def test_propose_changeset_detects_claim_withdrawal():
    cs = propose_changeset(
        entity_type="claim",
        old_version_id="v1",
        new_version_id="v2",
        old_label="",
        new_label="",
        old_claim="Clinically proven",
        new_claim="",
    )
    assert any(op.type == OP_CLAIM_WITHDRAWAL for op in cs.operations)


def test_propose_changeset_infers_visual_change_from_phash_distance():
    # Two very different perceptual hashes -> inferred visual change, flagged.
    cs = propose_changeset(
        entity_type="product_package",
        old_version_id="v1",
        new_version_id="v2",
        old_label="x",
        new_label="x",
        old_claim="x",
        new_claim="x",
        old_phash="ffffffffffffffff",
        new_phash="ffffffffffff0000",
    )
    visual = [op for op in cs.operations if op.type == OP_REPLACE_VISUAL]
    assert visual and visual[0].inferred and visual[0].confidence < 1.0
