# Innovation Proof

The invention is the *decision pipeline*, not the image provider:

> TRUTH → SEMANTIC DELTA → CAUSAL IMPACT → RECONCILIATION PROGRAM → EXECUTION → VERIFICATION → PROOF

Every claim below is backed by an executable test over the **unchanged production
engine** (`rusted_recall/{changeset,graph,evidence,propagation,planner,services}.py`).
None of these tests contain company names, IDs, or expected-answer tables in the
decision path.

## 1. Causal semantics, not reachability
Impact is computed from dependency graph + edge semantics + evidence, and edge
semantics gate propagation. A visually-similar but disconnected asset is `safe`;
a connected asset can be affected via a typed edge.
- `tests/test_propagation.py`, `tests/test_graph.py`
- `tests/test_generalisation.py::test_disconnected_asset_stays_safe`

## 2. Global-optimal reconciliation program (vs local per-asset repair)
Given a shared ancestor with deterministic descendants, the planner repairs the
ancestor **once** and rebuilds descendants deterministically instead of
regenerating each independently.
- `tests/test_innovation.py::test_global_optimum_beats_local_repair`
  → naive 4 generative ops vs Rusted **1 generative + 3 deterministic rebuilds**, 3 avoided.

## 3. Counterfactual planning (decisions respond to topology, no code change)
Removing the derivation relationship flips the plan from "repair once + rebuild"
to "generate each".
- `tests/test_innovation.py::test_decision_changes_when_topology_changes`

## 4. Generation necessity
Generation is selected only when the change requires new imagery; a pure text
change reconciles deterministically with **zero** generative operations.
- `tests/test_innovation.py::test_generative_necessity_depends_on_change_semantics`

## 5. Provider independence
Analysis + planning succeed with **no provider configured**; a required
generative op then fails **honestly** (`error_category=authentication`), never
fabricated. GMI/Seedream is an executor, not the brain.
- `tests/test_innovation.py::test_engine_reasons_without_any_provider`

## 6. Fixpoint / idempotence
Once reconciled, re-running produces no new versions/jobs (terminal no-op);
duplicate repair requests never create duplicate work.
- `tests/test_innovation.py::test_reconciliation_is_idempotent_at_fixpoint`
- `tests/test_retry_idempotency.py::test_idempotent_repeated_repair`

## 7. Blind generalisation
A generic company ("Zephyr Instruments") built entirely through the same public
`services` the web UI uses — no seed, no code change — yields a differentiated,
explainable impact set and an inferred repair DAG.
- `tests/test_innovation.py::test_blind_company_generalises_without_code_changes`

## 8. Baseline benchmark + scale
See `evidence/BENCHMARK_RESULTS.json` (`scripts/benchmark.py`). Planner scales to
10,000 assets in ~0.06s and avoids 8,000 generative ops on that synthetic graph.
