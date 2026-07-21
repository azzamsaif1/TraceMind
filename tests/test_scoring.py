from rusted_recall.config import validate_scoring_config
from rusted_recall.scoring import ScoreComponents, classify, compute_evidence_score


def test_scoring_config_is_valid():
    validate_scoring_config()  # must not raise


def test_evidence_score_weighted_sum():
    comp = ScoreComponents(structural_dependency=1.0)
    assert compute_evidence_score(comp) == 0.30
    comp = ScoreComponents(visual_evidence=1.0, text_evidence=1.0)
    assert round(compute_evidence_score(comp), 6) == 0.35


def test_confirmed_dependency_overrides_to_directly_affected():
    r = classify(ScoreComponents(), confirmed_dependency=True)
    assert r.classification == "directly_affected"
    assert r.confirmed_dependency is True


def test_directly_affected_by_high_score():
    comp = ScoreComponents(
        structural_dependency=1.0,
        visual_evidence=1.0,
        text_evidence=1.0,
        semantic_evidence=1.0,
    )
    r = classify(comp)
    assert r.impact_score >= 0.80
    assert r.classification == "directly_affected"


def test_probably_affected_band():
    # evidence in [0.55, 0.80)
    comp = ScoreComponents(structural_dependency=1.0, visual_evidence=1.0, semantic_evidence=0.7)
    r = classify(comp)
    assert 0.55 <= r.impact_score < 0.80
    assert r.classification == "probably_affected"


def test_needs_review_band():
    comp = ScoreComponents(visual_evidence=0.8, semantic_evidence=0.6)
    r = classify(comp)
    assert 0.25 <= r.impact_score < 0.55
    assert r.classification == "needs_review"


def test_conflicting_evidence_forces_review():
    comp = ScoreComponents(visual_evidence=1.0)
    r = classify(comp, conflicting_evidence=True)
    assert r.classification == "needs_review"


def test_safe_when_low_and_no_dependency():
    r = classify(ScoreComponents(semantic_evidence=0.1))
    assert r.classification == "safe"
    assert r.impact_score < 0.25


def test_market_applicability_reduces_score():
    comp = ScoreComponents(structural_dependency=1.0, visual_evidence=1.0, text_evidence=1.0)
    full = classify(comp)
    reduced = classify(comp, market_applicability=0.5)
    assert reduced.impact_score < full.impact_score


def test_components_preserved_in_result():
    comp = ScoreComponents(structural_dependency=0.5, visual_evidence=0.3)
    r = classify(comp)
    assert r.components["structural_dependency"] == 0.5
    assert r.components["visual_evidence"] == 0.3
    assert r.reasons  # explanation present
