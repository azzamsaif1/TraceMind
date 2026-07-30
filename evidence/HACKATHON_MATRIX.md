# Rusted Recall — Release Matrix

Legend: **PASS** = executable evidence exists (cited). **BLOCKED** = cannot be
proven now; exact owner action given. Nothing is marked PASS on the strength of
UI text, mocks, or hardcoded values.

Reproduce the automated evidence:

```bash
.venv/bin/ruff check rusted_recall tests scripts
.venv/bin/mypy rusted_recall
APP_ENV=test STORAGE_BACKEND=local DATABASE_URL="sqlite:////tmp/rr_test.db" \
  B2_KEY_ID="" B2_APP_KEY="" B2_BUCKET_NAME="" \
  GMICLOUD_API_KEY="" OPENAI_API_KEY="" \
  .venv/bin/python -m pytest -p no:cacheprovider -o addopts="" -q
```

Result on this branch: **ruff clean · mypy clean (39 files) · 146 passed, 2 skipped**.

| Capability | Status | Evidence |
|---|---|---|
| ChangeSet semantics | PASS | `tests/test_changeset.py`, `tests/test_usage_changeset_integration.py` |
| Causal propagation (not reachability) | PASS | `tests/test_propagation.py`, `tests/test_graph.py` |
| Explainable impact + causal paths | PASS | `tests/test_generalisation.py::test_declared_master_is_directly_affected_with_causal_path` |
| MinimalRepairPlanner | PASS | `tests/test_planner.py`, `tests/test_innovation.py` |
| Global-optimal repair (vs local) | PASS | `tests/test_innovation.py::test_global_optimum_beats_local_repair` |
| Counterfactual planning (topology-driven) | PASS | `tests/test_innovation.py::test_decision_changes_when_topology_changes` |
| Generative necessity | PASS | `tests/test_innovation.py::test_generative_necessity_depends_on_change_semantics` |
| Deterministic descendant rebuild | PASS | `tests/test_planner.py::test_deterministic_children_are_rebuilt_not_regenerated` |
| Independent creative child → separate repair | PASS | `tests/test_planner.py::test_independent_assets_all_need_generative` |
| Cycles terminate safely | PASS | `tests/test_graph.py::test_cycle_is_safe` |
| Disconnected node stays safe | PASS | `tests/test_generalisation.py::test_disconnected_asset_stays_safe` |
| Graph mutation changes result (no code change) | PASS | `graph_mutation_proof.py`, `tests/test_propagation.py` |
| Blind generalisation (generic company) | PASS | `tests/test_innovation.py::test_blind_company_generalises_without_code_changes` |
| Provider independence | PASS | `tests/test_innovation.py::test_engine_reasons_without_any_provider` |
| Fixpoint / idempotence | PASS | `tests/test_innovation.py::test_reconciliation_is_idempotent_at_fixpoint`, `tests/test_retry_idempotency.py` |
| FSM: partially_completed → repairing (retry) | PASS | `tests/test_recall_state_machine.py`, `tests/test_retry_idempotency.py::test_retry_failed_only_and_fsm` |
| FSM: no illegal same-state transition | PASS | `tests/test_recall_state_machine.py::test_no_illegal_same_state_partial_transition` |
| Retry failed-only (preserve successes/versions) | PASS | `tests/test_retry_idempotency.py` |
| Provider error taxonomy (401/402/403/404/408/422/429/451/5xx/timeout/corrupt) | PASS | `tests/test_provider_errors.py`, `tests/test_gmicloud.py` |
| Retryable vs permanent classification | PASS | `tests/test_provider_errors.py::test_retryability_contract` |
| Official Genblaze SDK wired (pinned) | PASS | `tests/test_genblaze_official.py`; genblaze-core 0.3.8 / genblaze-gmicloud 0.3.5 |
| Durable repair queue (persisted) | PASS | `tests/test_worker_queue.py::test_queue_survives_new_process` |
| Separate-worker code + entrypoint | PASS | `rusted_recall/worker.py` (`python -m rusted_recall.worker`), `render.yaml` |
| Worker enqueue de-dup | PASS | `tests/test_worker_queue.py::test_enqueue_dedups_active_items` |
| Atomic claim (SKIP LOCKED) on real Postgres | PASS | `scripts/pg_claim_proof.py` → `items=5 successful_claims=5 unique=5` |
| Stale-claim recovery + bounded retries | PASS | `tests/test_worker_queue.py::test_stale_claim_recovered` |
| Worker restart safety | PASS | `tests/test_worker_queue.py::test_queue_survives_new_process` |
| Provider failure honest (no fake success) | PASS | `tests/test_worker_queue.py::test_run_once_provider_failure_is_honest` |
| Alembic migration chain on Postgres | PASS | `alembic upgrade head` on postgres:16 (initial → 15fabd319801 → 2b7c9d1e4f10); downgrade/re-upgrade verified |
| Real B2 write / read-back / hash / no-overwrite / presigned | PASS | `scripts/b2_proof.py` → `evidence/B2_PROOF.json` (`result: PASS`) against bucket `Tracemind-storage` |
| Baseline benchmark + scale | PASS | `scripts/benchmark.py` → `evidence/BENCHMARK_RESULTS.json` |
| Diagnostics: configured vs verified + queue depth | PASS | `/diagnostics` renders worker mode + `queued/claimed/done/failed` |
| Public HTTPS deploy of THIS branch | BLOCKED | Merge PR, then Render auto-deploys `https://rusted-recall.onrender.com`. |
| Separate worker **deployed** on Render | BLOCKED | Apply `render.yaml` as a Render Blueprint (adds `rusted-recall-worker`) and set web `RUN_INLINE_WORKER=false`. Until then the single web dyno drains its own durable queue inline (functional, not horizontally scaled). |
| Real GMI Seedream generation | BLOCKED | Add credits at https://console.gmicloud.ai → Billing. Live call returns HTTP 402 "Insufficient credits" (classified `quota`). |
| Generated output / validation of real output | BLOCKED | Depends on GMI credits. |
| Golden Production Recall (real gen) | BLOCKED | Depends on GMI credits + deploy. |
| Unseen Production Recall (real gen) | BLOCKED | Depends on GMI credits + deploy. |

## Exact owner actions to clear all BLOCKED items
1. **Add GMI credits** at https://console.gmicloud.ai (Billing). This is the only thing blocking real generation and the Golden/Unseen production recalls.
2. **Rotate the B2 / GMI / OpenAI keys** pasted into chat — treat them as compromised.
3. **Deploy this branch** (merge the PR; Render redeploys the web service).
4. **(Recommended) Apply `render.yaml`** as a Render Blueprint to run the dedicated `rusted-recall-worker` service and set `RUN_INLINE_WORKER=false` on web.

## The single paid end-to-end test to run once credits exist
Against `https://rusted-recall.onrender.com`, from the judge flow: **Run Live Recall → Approve → Repair** on the LumaLeaf/Northstar generative asset (or any campaign whose plan contains a `GENERATIVE_REPAIR`). Then confirm on `/diagnostics` + `/submission-evidence`: provider "verified working", a `GenerationRun` with a real upstream request id + genblaze versions, a new immutable `AssetVersion` (origin=`repaired`) with B2 read-back SHA match, manifest + lineage + audit event, and the original preserved.
