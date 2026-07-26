"""Change Propagation Engine (spec sections 15-17).

A dedicated domain component that consumes a :class:`~rusted_recall.changeset.ChangeSet`,
a dependency-graph snapshot and the evidence edges into each asset, and produces
an :class:`ImpactSet`. Every impacted asset carries an explainable score, the
strongest causal path, a human-readable *why this asset?* explanation, the
propagation reason, and its repair/review requirement.

The engine is pure (no database, no I/O) so it is fully unit-testable. The
services layer adapts persisted rows into its inputs and persists its outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rusted_recall import evidence as ev
from rusted_recall.changeset import ChangeSet
from rusted_recall.graph import DependencyGraph, Path
from rusted_recall.scoring import ImpactResult, ScoreComponents, classify

# Edge types that always represent a real structural dependency regardless of
# the change operation (an explicit/manifest link means the asset genuinely uses
# the source; a parent-child link means it is a real derivative).
_ALWAYS_STRUCTURAL = frozenset({ev.EDGE_EXPLICIT, ev.EDGE_MANIFEST, ev.EDGE_PARENT_CHILD})


@dataclass(frozen=True)
class EdgeInput:
    """Evidence edge into an asset (adapter over a persisted DependencyEdge)."""

    edge_type: str
    confidence: float
    human_confirmed: bool = False


@dataclass(frozen=True)
class AssetInput:
    """Minimal asset facts the engine needs (adapter over persisted Asset)."""

    id: str
    name: str
    publication_status: str = "draft"
    in_market: bool = True


@dataclass
class ImpactItem:
    asset_id: str
    classification: str
    impact_score: float
    evidence_score: float
    components: dict[str, float]
    reasons: list[str]
    strongest_path: dict
    propagation_reason: str
    causal_explanation: str
    repair_requirement: str
    review_requirement: bool
    distribution_risk: str
    confirmed_dependency: bool

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "classification": self.classification,
            "impact_score": round(self.impact_score, 6),
            "evidence_score": round(self.evidence_score, 6),
            "components": self.components,
            "reasons": self.reasons,
            "strongest_path": self.strongest_path,
            "propagation_reason": self.propagation_reason,
            "causal_explanation": self.causal_explanation,
            "repair_requirement": self.repair_requirement,
            "review_requirement": self.review_requirement,
            "distribution_risk": self.distribution_risk,
            "confirmed_dependency": self.confirmed_dependency,
        }


@dataclass
class ImpactSet:
    items: list[ImpactItem] = field(default_factory=list)

    def by_classification(self, classification: str) -> list[ImpactItem]:
        return [i for i in self.items if i.classification == classification]

    def as_dict(self) -> dict:
        return {"items": [i.as_dict() for i in self.items]}


def components_from_edges(
    edges: list[EdgeInput],
) -> tuple[ScoreComponents, bool, bool]:
    """Map evidence edges onto explainable score components.

    Returns ``(components, confirmed_dependency, conflicting_evidence)``.
    """
    comp = ScoreComponents()
    confirmed = False
    for e in edges:
        c = e.confidence
        if e.edge_type in (ev.EDGE_EXPLICIT, ev.EDGE_MANIFEST):
            comp.structural_dependency = max(comp.structural_dependency, c)
            if e.human_confirmed:
                confirmed = True
        elif e.edge_type == ev.EDGE_PARENT_CHILD:
            comp.structural_dependency = max(comp.structural_dependency, c)
            comp.derivation_evidence = max(comp.derivation_evidence, c)
        elif e.edge_type == ev.EDGE_SHA256_DUPLICATE:
            comp.visual_evidence = max(comp.visual_evidence, c)
            comp.derivation_evidence = max(comp.derivation_evidence, c)
        elif e.edge_type == ev.EDGE_PHASH_DERIVATIVE:
            comp.visual_evidence = max(comp.visual_evidence, c)
            comp.derivation_evidence = max(comp.derivation_evidence, c)
        elif e.edge_type == ev.EDGE_VISUAL:
            comp.visual_evidence = max(comp.visual_evidence, c)
        elif e.edge_type == ev.EDGE_OCR_TEXT:
            comp.text_evidence = max(comp.text_evidence, c)
        elif e.edge_type == ev.EDGE_SEMANTIC:
            comp.semantic_evidence = max(comp.semantic_evidence, c)
        if e.human_confirmed:
            comp.human_confirmation = max(comp.human_confirmation, 1.0)
    conflicting = comp.structural_dependency == 0 and (
        0 < comp.visual_evidence < 0.6
        and comp.text_evidence == 0
        and comp.semantic_evidence == 0
    )
    return comp, confirmed, conflicting


class ChangePropagationEngine:
    """Compute the ImpactSet for a change (spec section 15)."""

    def __init__(self, changeset: ChangeSet | None) -> None:
        self.changeset = changeset

    def _allowed_edge_types(self) -> frozenset[str] | None:
        """Edge types eligible for propagation under this ChangeSet.

        When no ChangeSet is available (unknown change) every edge type is
        eligible — we degrade to breadth rather than fabricate precision.
        """
        if self.changeset is None or self.changeset.is_empty:
            return None
        return frozenset(self.changeset.propagating_edge_types() | _ALWAYS_STRUCTURAL)

    def _eligible_edges(self, edges: list[EdgeInput]) -> list[EdgeInput]:
        allowed = self._allowed_edge_types()
        if allowed is None:
            return edges
        return [e for e in edges if e.edge_type in allowed]

    def _repair_requirement(
        self, classification: str, edges: list[EdgeInput]
    ) -> str:
        if classification in ("safe",):
            return "none"
        if classification == "needs_review":
            return "manual_review"
        # A visual change to an asset that is a deterministic derivative can be
        # rebuilt rather than regenerated; the Minimal Repair Planner decides
        # this per asset. Here we surface the generative-vs-deterministic hint.
        if self.changeset is not None and self.changeset.requires_generative_repair:
            has_derivation = any(
                e.edge_type in (ev.EDGE_PARENT_CHILD,) for e in edges
            )
            return "deterministic_or_generative" if has_derivation else "generative"
        return "text_overlay"

    def compute(
        self,
        *,
        source_node: str,
        graph: DependencyGraph,
        assets: list[AssetInput],
        edges_by_target: dict[str, list[EdgeInput]],
        node_labels: dict[str, str] | None = None,
    ) -> ImpactSet:
        labels = node_labels or {}
        allowed = self._allowed_edge_types()
        paths = graph.strongest_paths(source_node, allowed_edge_types=allowed)

        result = ImpactSet()
        for asset in assets:
            node = f"asset:{asset.id}"
            raw_edges = edges_by_target.get(node, [])
            edges = self._eligible_edges(raw_edges)
            comp, confirmed, conflicting = components_from_edges(edges)

            path = paths.get(node)
            reachable = path is not None
            applicability = 1.0 if asset.in_market else 0.0
            active = 1.0 if asset.publication_status in ("published", "active") else 0.85

            no_evidence = (
                comp.structural_dependency == 0
                and comp.visual_evidence == 0
                and comp.text_evidence == 0
                and comp.semantic_evidence == 0
            )
            if not reachable and no_evidence:
                impact: ImpactResult = classify(
                    ScoreComponents(), market_applicability=applicability
                )
            else:
                impact = classify(
                    comp,
                    market_applicability=applicability,
                    active_distribution_factor=active,
                    confirmed_dependency=confirmed,
                    conflicting_evidence=conflicting,
                )

            propagation_reason = self._propagation_reason(edges)
            causal = self._causal_explanation(impact.classification, path, edges, labels)
            distribution_risk = (
                "high"
                if asset.publication_status in ("published", "active")
                and impact.classification in ("directly_affected", "probably_affected")
                else "low"
            )

            result.items.append(
                ImpactItem(
                    asset_id=asset.id,
                    classification=impact.classification,
                    impact_score=impact.impact_score,
                    evidence_score=impact.evidence_score,
                    components=impact.components,
                    reasons=impact.reasons,
                    strongest_path=_path_dict(path, node),
                    propagation_reason=propagation_reason,
                    causal_explanation=causal,
                    repair_requirement=self._repair_requirement(impact.classification, edges),
                    review_requirement=impact.classification == "needs_review",
                    distribution_risk=distribution_risk,
                    confirmed_dependency=confirmed,
                )
            )
        # Strongest impact first.
        result.items.sort(key=lambda i: i.impact_score, reverse=True)
        return result

    def _propagation_reason(self, edges: list[EdgeInput]) -> str:
        if not edges:
            return "no eligible dependency for this change type"
        if self.changeset is None or self.changeset.is_empty:
            kinds = sorted({e.edge_type for e in edges})
            return "evidence via " + ", ".join(kinds)
        ops = "; ".join(op.type.replace("_", " ") for op in self.changeset.operations)
        kinds = sorted({e.edge_type for e in edges})
        return f"change ({ops}) propagates through {', '.join(kinds)}"

    def _causal_explanation(
        self,
        classification: str,
        path: Path | None,
        edges: list[EdgeInput],
        labels: dict[str, str],
    ) -> str:
        if classification == "safe":
            return "No eligible dependency and no significant evidence for this change."
        if path is not None and path.edges:
            chain = " -> ".join(
                f"{labels.get(n, n.split(':', 1)[-1][:8])}" for n in path.nodes
            )
            edge_types = ", ".join(e.edge_type for e in path.edges)
            return (
                f"Affected via dependency chain {chain} "
                f"(edges: {edge_types})."
            )
        if edges:
            details = ", ".join(f"{e.edge_type}={round(e.confidence, 2)}" for e in edges)
            return (
                "No explicit dependency chain; classified from evidence "
                f"({details})."
            )
        return "Insufficient confidence for automatic repair; human review required."


def _path_dict(path: Path | None, node: str) -> dict:
    if path is None:
        return {"nodes": [node], "edges": [], "strength": 0.0, "describe": node}
    return {
        "nodes": path.nodes,
        "edges": [{"type": e.edge_type, "confidence": e.confidence} for e in path.edges],
        "strength": path.strength,
        "describe": path.describe(),
    }
