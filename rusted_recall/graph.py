"""Dependency-graph traversal for impact analysis (directive section 12).

Supports direct and multi-hop edges, cycle-safe traversal, a maximum path depth,
per-hop confidence decay, multiple independent paths, and returning the strongest
explanation path for each impacted asset.
"""
from __future__ import annotations

from dataclasses import dataclass

from rusted_recall.config import GRAPH_EDGE_DECAY, GRAPH_MAX_DEPTH


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    edge_type: str
    confidence: float


@dataclass
class Path:
    nodes: list[str]
    edges: list[Edge]
    # Aggregated confidence after per-hop decay.
    strength: float

    @property
    def depth(self) -> int:
        return len(self.edges)

    def describe(self) -> str:
        parts = [self.nodes[0]]
        for e in self.edges:
            parts.append(f"--[{e.edge_type} {round(e.confidence, 2)}]-->")
            parts.append(e.target)
        return " ".join(parts)


class DependencyGraph:
    def __init__(self) -> None:
        self._out: dict[str, list[Edge]] = {}

    def add_edge(self, source: str, target: str, edge_type: str, confidence: float) -> None:
        self._out.setdefault(source, []).append(
            Edge(source=source, target=target, edge_type=edge_type, confidence=max(0.0, min(1.0, confidence)))
        )

    def neighbors(self, node: str) -> list[Edge]:
        return self._out.get(node, [])

    def strongest_paths(
        self, start: str, *, max_depth: int = GRAPH_MAX_DEPTH, decay: float = GRAPH_EDGE_DECAY
    ) -> dict[str, Path]:
        """Return the single strongest path from ``start`` to every reachable node.

        Strength = product of edge confidences with a geometric per-hop decay.
        Cycle-safe: a node is not revisited within the same path.
        """
        best: dict[str, Path] = {}

        def visit(node: str, nodes: list[str], edges: list[Edge], strength: float) -> None:
            if len(edges) >= max_depth:
                return
            for edge in self.neighbors(node):
                if edge.target in nodes:  # avoid cycles within this path
                    continue
                hop_strength = strength * edge.confidence * (decay ** len(edges))
                new_nodes = nodes + [edge.target]
                new_edges = edges + [edge]
                existing = best.get(edge.target)
                if existing is None or hop_strength > existing.strength:
                    best[edge.target] = Path(nodes=new_nodes, edges=new_edges, strength=hop_strength)
                visit(edge.target, new_nodes, new_edges, hop_strength)

        visit(start, [start], [], 1.0)
        return best

    def reachable(self, start: str, *, max_depth: int = GRAPH_MAX_DEPTH) -> set[str]:
        return set(self.strongest_paths(start, max_depth=max_depth).keys())
