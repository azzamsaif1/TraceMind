"""Explainable change-impact scoring (directive section 12).

The score is never an opaque number: every component value is preserved and the
classification rule that fired is returned alongside the score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rusted_recall.config import EVIDENCE_WEIGHTS, IMPACT_THRESHOLDS

CLASSIFICATIONS = ("directly_affected", "probably_affected", "needs_review", "safe")


@dataclass
class ScoreComponents:
    """Individual evidence-component scores, each in [0, 1]."""

    structural_dependency: float = 0.0
    visual_evidence: float = 0.0
    text_evidence: float = 0.0
    semantic_evidence: float = 0.0
    derivation_evidence: float = 0.0
    human_confirmation: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "structural_dependency": self.structural_dependency,
            "visual_evidence": self.visual_evidence,
            "text_evidence": self.text_evidence,
            "semantic_evidence": self.semantic_evidence,
            "derivation_evidence": self.derivation_evidence,
            "human_confirmation": self.human_confirmation,
        }


@dataclass
class ImpactResult:
    evidence_score: float
    impact_score: float
    classification: str
    components: dict[str, float]
    weights: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    confirmed_dependency: bool = False
    market_applicability: float = 1.0
    active_distribution_factor: float = 1.0

    def as_dict(self) -> dict:
        return {
            "evidence_score": round(self.evidence_score, 6),
            "impact_score": round(self.impact_score, 6),
            "classification": self.classification,
            "components": {k: round(v, 6) for k, v in self.components.items()},
            "weights": self.weights,
            "reasons": self.reasons,
            "confirmed_dependency": self.confirmed_dependency,
            "market_applicability": self.market_applicability,
            "active_distribution_factor": self.active_distribution_factor,
        }


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_evidence_score(components: ScoreComponents) -> float:
    """Weighted sum of the evidence components (weights sum to 1.0)."""
    comp = components.as_dict()
    return sum(EVIDENCE_WEIGHTS[name] * _clamp(value) for name, value in comp.items())


def classify(
    components: ScoreComponents,
    *,
    market_applicability: float = 1.0,
    active_distribution_factor: float = 1.0,
    confirmed_dependency: bool = False,
    conflicting_evidence: bool = False,
) -> ImpactResult:
    """Compute the explainable impact score and classification.

    A confirmed, explicit dependency is a high-priority rule that overrides the
    weighted score to ``directly_affected`` (directive section 12).
    """
    market_applicability = _clamp(market_applicability)
    active_distribution_factor = _clamp(active_distribution_factor)

    evidence_score = compute_evidence_score(components)
    impact_score = evidence_score * market_applicability * active_distribution_factor

    reasons: list[str] = []
    comp = components.as_dict()
    for name, value in sorted(comp.items(), key=lambda kv: kv[1], reverse=True):
        if value > 0:
            reasons.append(f"{name}={round(value, 3)} (weight {EVIDENCE_WEIGHTS[name]})")

    t = IMPACT_THRESHOLDS
    if confirmed_dependency:
        classification = "directly_affected"
        reasons.insert(0, "confirmed explicit dependency overrides weighted score")
    elif impact_score >= t["directly_affected"]:
        classification = "directly_affected"
    elif impact_score >= t["probably_affected"]:
        classification = "probably_affected"
    elif conflicting_evidence or impact_score >= t["needs_review"]:
        classification = "needs_review"
        if conflicting_evidence:
            reasons.append("conflicting evidence flagged for review")
    else:
        classification = "safe"
        reasons.append("below needs_review threshold and no confirmed dependency")

    return ImpactResult(
        evidence_score=evidence_score,
        impact_score=impact_score,
        classification=classification,
        components=comp,
        weights=dict(EVIDENCE_WEIGHTS),
        reasons=reasons,
        confirmed_dependency=confirmed_dependency,
        market_applicability=market_applicability,
        active_distribution_factor=active_distribution_factor,
    )
