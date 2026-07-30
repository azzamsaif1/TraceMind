# Fixpoint & Idempotence Proof

**Claim:** duplicate repair requests, retries, worker restarts, and repeated
processing cannot create duplicate repairs, jobs, versions, manifests, or
provider charges; a reconciled recall is a terminal no-op.

## Idempotency key
`rusted_recall/repair.py::compute_idempotency_key` hashes
`(recall, asset_version, plan_version, provider, model, params)`. Stable and
order-independent.
- `tests/test_repair.py::{test_idempotency_key_is_stable,test_idempotency_key_order_independent_for_params,test_idempotency_key_changes_with_inputs}`

## Reconciliation is idempotent (application boundary)
Running `approve_and_repair` twice creates no new repaired versions / plans /
jobs. `execute_repair_job` short-circuits on an existing completed job with the
same idempotency key.
- `tests/test_retry_idempotency.py::test_idempotent_repeated_repair`
- `tests/test_innovation.py::test_reconciliation_is_idempotent_at_fixpoint`

## Retry is failed-only, and the FSM is legal
A first attempt against a failing provider → all jobs `failed`, recall
`partially_completed`. Retry with a working provider transitions
`partially_completed → repairing` (no `IllegalTransitionError`), retries only the
failed retryable work, preserves successes/versions, then derives `completed`.
- `tests/test_retry_idempotency.py::test_retry_failed_only_and_fsm`
- `tests/test_recall_state_machine.py::{test_partial_can_retry_via_repairing,test_no_illegal_same_state_partial_transition}`

## Durable queue: restart & duplicate safety
- Enqueue de-dups an active recall to a single durable item — `tests/test_worker_queue.py::test_enqueue_dedups_active_items`
- The item survives an engine reset (process restart) — `::test_queue_survives_new_process`
- Re-enqueue + re-run after completion adds no duplicate versions/jobs — `::test_run_once_processes_and_is_idempotent`
- A provider failure leaves the recall `partially_completed` (never fake `completed`) — `::test_run_once_provider_failure_is_honest`

## Charge safety
Because execution is idempotent and the unit of work is the whole recall, a
crashed-then-retried claim re-runs `approve_and_repair`, which reuses completed
jobs and never re-invokes the provider for already-repaired assets → **no
duplicate provider charges**.
