# Counterfactual Planning Proof

**Claim:** the MinimalRepairPlanner computes the *smallest justified* set of
operations, and its output changes with topology and repairability — it is not a
fixed `asset_type → method` table.

## Same assets, different topology → different plan
`tests/test_innovation.py::test_decision_changes_when_topology_changes`

```
derived:      root(generative) ── crop c1     →  1 generative, 1 deterministic, 1 avoided
independent:  root, c1 (no relationship)       →  2 generative, 0 deterministic, 0 avoided
```

The only difference between the two inputs is the derivation edge. The plan
responds to the graph, proving counterfactual (topology-driven) planning.

## Global optimum beats local repair
`tests/test_innovation.py::test_global_optimum_beats_local_repair`
```
root + c1(crop) + c2(resize) + c3(crop)
naive/local:  4 generative operations (one per asset)
Rusted:       1 generative (root) + 3 deterministic rebuilds, 3 avoided
```

## Generation only when required
`tests/test_innovation.py::test_generative_necessity_depends_on_change_semantics`
- `requires_generative=True`  → root method `controlled_regeneration`
- `requires_generative=False` (pure text) → 0 generative, deterministic overlay

## Method selection per node
`tests/test_planner.py::test_deterministic_children_are_rebuilt_not_regenerated`,
`::test_child_of_non_repaired_parent_is_generative`,
`::test_needs_review_asset_is_manual`.

Supported actions: `NO_OP / DETERMINISTIC_TRANSFORM (crop/resize/overlay) /
REBUILD_FROM_PARENT / GENERATIVE_REPAIR / HUMAN_REVIEW`. Correctness and
provenance are hard constraints; cost/fan-out/repairability drive the choice.

## Scale
`evidence/BENCHMARK_RESULTS.json → scale_test`: 10 / 100 / 1000 / 10000 assets;
at 10k the planner selects 2,000 generative + 8,000 deterministic rebuilds
(8,000 avoided) in ~0.06s.
