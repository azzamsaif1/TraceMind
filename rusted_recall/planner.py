"""Minimal Repair Planner (spec section 18).

A central differentiator: instead of independently regenerating every affected
asset, the planner identifies deterministic derivatives (crops, resizes, format
variants) that can be rebuilt from a repaired parent, and only issues generative
operations for the roots of each derivation tree. It produces an execution DAG
and the real, calculated savings (never hardcoded — spec section 18).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Repair methods (spec section 19).
METHOD_GENERATIVE_EDIT = "generative_edit"
METHOD_CONTROLLED_REGENERATION = "controlled_regeneration"
METHOD_DETERMINISTIC_CROP = "deterministic_crop"
METHOD_DETERMINISTIC_RESIZE = "deterministic_resize"
METHOD_TEXT_OVERLAY = "text_overlay"
METHOD_MANUAL_REVIEW = "manual_review"

_GENERATIVE_METHODS = frozenset(
    {METHOD_GENERATIVE_EDIT, METHOD_CONTROLLED_REGENERATION}
)
_DETERMINISTIC_METHODS = frozenset(
    {METHOD_DETERMINISTIC_CROP, METHOD_DETERMINISTIC_RESIZE}
)

# Derivation methods that can be deterministically reconstructed from a repaired
# parent without a generative model call.
_DETERMINISTIC_DERIVATIONS = {
    "crop": METHOD_DETERMINISTIC_CROP,
    "cropped_from": METHOD_DETERMINISTIC_CROP,
    "resize": METHOD_DETERMINISTIC_RESIZE,
    "resized_from": METHOD_DETERMINISTIC_RESIZE,
}


@dataclass(frozen=True)
class PlannerAsset:
    """An asset that needs repair, plus its derivation facts."""

    id: str
    name: str = ""
    parent_asset_id: str | None = None
    derivation_method: str | None = None  # crop | resize | None (independent)
    needs_review: bool = False


@dataclass
class RepairNode:
    asset_id: str
    name: str
    method: str
    parent_asset_id: str | None
    reason: str

    @property
    def is_generative(self) -> bool:
        return self.method in _GENERATIVE_METHODS

    @property
    def is_deterministic(self) -> bool:
        return self.method in _DETERMINISTIC_METHODS

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "method": self.method,
            "parent_asset_id": self.parent_asset_id,
            "reason": self.reason,
        }


@dataclass
class RepairPlanGraph:
    nodes: list[RepairNode] = field(default_factory=list)
    naive_generative_operations: int = 0
    generative_operations: int = 0
    deterministic_rebuilds: int = 0
    manual_reviews: int = 0
    operations_avoided: int = 0

    def execution_dag(self) -> dict[str, list[str]]:
        """Adjacency: parent asset id -> list of child asset ids to rebuild."""
        adj: dict[str, list[str]] = {n.asset_id: [] for n in self.nodes}
        for n in self.nodes:
            if n.parent_asset_id and n.parent_asset_id in adj:
                adj[n.parent_asset_id].append(n.asset_id)
        return adj

    def generative_nodes(self) -> list[RepairNode]:
        return [n for n in self.nodes if n.is_generative]

    def as_dict(self) -> dict:
        return {
            "nodes": [n.as_dict() for n in self.nodes],
            "naive_generative_operations": self.naive_generative_operations,
            "generative_operations": self.generative_operations,
            "deterministic_rebuilds": self.deterministic_rebuilds,
            "manual_reviews": self.manual_reviews,
            "operations_avoided": self.operations_avoided,
            "execution_dag": self.execution_dag(),
        }


class MinimalRepairPlanner:
    def plan(
        self,
        assets: list[PlannerAsset],
        *,
        requires_generative: bool = True,
    ) -> RepairPlanGraph:
        """Compute the minimal repair execution DAG.

        ``requires_generative`` reflects whether the ChangeSet touches imagery
        (generative repair) or is a pure text change (deterministic overlay).
        An asset is a deterministic rebuild when it derives (crop/resize) from
        another asset that is itself in the repair set — rebuilding it from the
        repaired parent reproduces it exactly, with no model call.
        """
        ids = {a.id for a in assets}
        by_id = {a.id: a for a in assets}

        def deterministically_derivable(asset: PlannerAsset) -> bool:
            method = (asset.derivation_method or "").lower()
            return (
                asset.parent_asset_id is not None
                and asset.parent_asset_id in ids
                and method in _DETERMINISTIC_DERIVATIONS
            )

        graph = RepairPlanGraph()
        for asset in assets:
            if asset.needs_review:
                method = METHOD_MANUAL_REVIEW
                reason = "insufficient confidence; requires human review"
                graph.manual_reviews += 1
            elif deterministically_derivable(asset):
                parent = by_id.get(asset.parent_asset_id or "")
                method = _DETERMINISTIC_DERIVATIONS[(asset.derivation_method or "").lower()]
                pname = parent.name if parent else asset.parent_asset_id
                reason = f"rebuilt deterministically from repaired parent '{pname}'"
                graph.deterministic_rebuilds += 1
            elif requires_generative:
                method = METHOD_CONTROLLED_REGENERATION
                reason = "root asset requires a generative repair"
                graph.generative_operations += 1
            else:
                method = METHOD_TEXT_OVERLAY
                reason = "pure text change applied deterministically"
                graph.deterministic_rebuilds += 1
            graph.nodes.append(
                RepairNode(
                    asset_id=asset.id,
                    name=asset.name,
                    method=method,
                    parent_asset_id=asset.parent_asset_id
                    if asset.parent_asset_id in ids
                    else None,
                    reason=reason,
                )
            )

        # Naive strategy = one generative operation per repairable asset
        # (everything except manual-review items).
        repairable = [a for a in assets if not a.needs_review]
        graph.naive_generative_operations = len(repairable)
        graph.operations_avoided = max(
            0, graph.naive_generative_operations - graph.generative_operations
        )
        return graph
