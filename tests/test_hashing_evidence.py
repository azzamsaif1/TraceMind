import pytest

from rusted_recall import evidence
from rusted_recall.hashing import (
    perceptual_hash_bytes,
    phash_distance,
    phash_similarity,
    sha256_bytes,
)


def test_sha256_deterministic(blue_png):
    assert sha256_bytes(blue_png) == sha256_bytes(blue_png)


def test_sha256_differs(blue_png, red_png):
    assert sha256_bytes(blue_png) != sha256_bytes(red_png)


def test_phash_identical_distance_zero(blue_png):
    p = perceptual_hash_bytes(blue_png)
    assert phash_distance(p, p) == 0
    assert phash_similarity(p, p) == 1.0


def test_sha256_duplicate_evidence(blue_png):
    s = sha256_bytes(blue_png)
    ev = evidence.sha256_duplicate(s, s)
    assert ev is not None
    assert ev.edge_type == evidence.EDGE_SHA256_DUPLICATE
    assert ev.confidence == 1.0


def test_no_duplicate_evidence_for_different(blue_png, red_png):
    assert evidence.sha256_duplicate(sha256_bytes(blue_png), sha256_bytes(red_png)) is None


def test_ocr_exact_claim_match():
    ev = evidence.ocr_text_match("Contains 24-Hour Vitality botanical blend", "24-Hour Vitality")
    assert ev is not None
    assert ev.edge_type == evidence.EDGE_OCR_TEXT


def test_ocr_no_match():
    assert evidence.ocr_text_match("totally unrelated words", "24-Hour Vitality") is None


def test_semantic_similarity():
    ev = evidence.semantic_similarity(
        "LumaLeaf botanical sparkling water hero advertisement",
        "LumaLeaf botanical sparkling water product package",
    )
    assert ev is not None
    assert 0 < ev.confidence <= 1.0


def test_explicit_and_parent_child_evidence():
    e = evidence.explicit_declaration(note="declared by user")
    assert e.human_confirmed is True
    pc = evidence.parent_child("p", "c")
    assert pc.details == {"parent": "p", "child": "c"}


def test_token_cosine_bounds():
    assert evidence.token_cosine("a b c", "a b c") == pytest.approx(1.0)
    assert evidence.token_cosine("a b", "c d") == 0.0
