# Generalisation Proof

**Claim:** the intelligence works on arbitrary new customer data — not just
LumaLeaf/Northstar — with no source-code changes, seed scripts, hard-coded
names, fixed classifications, or fixed counts.

## Shared engine
LumaLeaf (`rusted_recall/demo/lumaleaf.py`) and Northstar
(`rusted_recall/demo/northstar.py`) both drive the SAME production services
(`services.register_source_of_truth` → `ingest_asset` → `add_source_version` →
`create_recall_event` → `run_impact_analysis` → `approve_and_repair`). The demo
modules only *seed data*; they never insert graph/impact/plan rows directly.
- `tests/test_generalisation.py`

## Blind generic company (no seed, generic names)
`tests/test_innovation.py` builds "Zephyr Instruments" through the public
services with generic asset names (Catalogue Master, Sidebar Crop, Trade Flyer,
Break Room Notice) and a claim change `Certified Titanium Body → Certified
Aerospace Alloy Body`. The engine, unchanged, produces:
- disconnected "Break Room Notice" → **safe**
- declared "Catalogue Master" → affected, with `causal_explanation` + `strongest_path`
- an inferred repair DAG (`naive_generative_operations ≥ generative_operations`)

## Differentiated real numbers (from `evidence/BENCHMARK_RESULTS.json`)
| Scenario | analysed | affected | safe | review | naive gen | Rusted gen | det. rebuilds | avoided |
|---|---|---|---|---|---|---|---|---|
| LumaLeaf | 6 | 1 | 4 | 1 | 1 | 0 | 1 | 1 |
| Northstar | 6 | 1 | 1 | 4 | 1 | 1 | 0 | 0 |
| Blind generic company | 4 | 2 | 1 | 1 | 2 | 0 | 2 | 2 |

Different topologies produce different classifications and different repair
programs — evidence the output is computed, not scripted.

## Graph mutation (normal product operations, no code change)
`graph_mutation_proof.py` runs a recall, removes a dependency edge, re-runs, then
adds an edge and re-runs; the affected set changes each time.

## Full customer workflow (product test)
"If all demo data were deleted, can a new company sign up, upload data, define
relationships, change a source, and receive a correct computed recall without
developer intervention?" — the blind-company test answers YES for the
compute+plan path. The only step not exercisable end-to-end right now is the
**real generative execution**, which is BLOCKED on GMI credits (see
`GENBLAZE_PROOF.md`), not on the engine.
