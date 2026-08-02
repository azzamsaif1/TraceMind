# Rusted Recall — Final Delivery Report

Semantic change-impact intelligence and automated reconciliation for
generative-media assets. The invention is the decision pipeline, not an image
generator:

> TRUTH → SEMANTIC DELTA → CAUSAL IMPACT → RECONCILIATION PROGRAM → EXECUTION → VERIFICATION → PROOF

Public app: `https://rusted-recall.onrender.com` · Repo: `azzamsaif1/TraceMind`

This report is written **after** executable verification. Capabilities that
cannot be proven now are marked **BLOCKED** with the exact owner action — none
are inflated to "done".

## Verified Opportunity, preflight, UX (PR #11, merged & deployed)
- **Verified Opportunity lifecycle** (spec §3) — machine-grounded, not LLM
  brainstorming. Each candidate passes `causal proof → constraint → feasibility
  → counterfactual → VERIFIED` over persisted state before it is surfaced.
  Rejection is truthful and specific (`no_causal_evidence`, `valid_before_change`);
  no executable path ⇒ `BLOCKED` (never fake success). `models.Opportunity` +
  migration `3c8e2f5a9b21` (verified on Postgres up/down/up).
  `services.discover_opportunities` (idempotent NO_OP re-scan) +
  `services.execute_opportunity` run through the SAME real engine: native ops
  stay native (zero provider calls, real immutable `AssetVersion`, B2
  write→read-back→SHA verify, manifest/provenance/validation, audit); generative
  ops route through the pipeline only when a provider is usable; partial results
  reported honestly. Web routes `POST /recalls/{id}/opportunities` +
  `POST /opportunities/{id}/execute`; UI in `recall_detail.html`.
- **Provider capability / preflight routing** (spec §2) —
  `providers/preflight.py` answers “can we generate now, and if not exactly why”
  with NO paid call. Typed states (`usable`, `insufficient_credits`,
  `authentication_failure`, `unsupported_model`, …) map 1:1 to the repair error
  taxonomy; surfaced on `/diagnostics` (live on the deployed site).
- **Product UX + contextual guidance** (spec §4) — every action has
  hover/focus/active/disabled/loading states + duplicate-submit prevention;
  `guidance.py` + Guide panel derive the next step from actual workspace state.
- **Native deterministic derivation reachable publicly** — the asset form now
  exposes a `derivation_method` selector (crop / resize) so a company can, with
  no source edit or SQL, declare a deterministic derivative that Rusted rebuilds
  from its repaired parent **natively (zero provider calls)** — both in normal
  repair and in Verified Opportunity execution.

## What was implemented in earlier delivery (continuation)
- **Durable, restart-safe repair queue + separate worker.** New
  `repair_queue_items` table + migration `2b7c9d1e4f10`; `rusted_recall/worker.py`
  (durable enqueue with de-dup, atomic claim via `SELECT ... FOR UPDATE SKIP
  LOCKED` on Postgres, bounded retries, stale-claim recovery, `run_forever`
  loop, `python -m rusted_recall.worker` entrypoint).
- **Web/worker split.** `jobs.py` now persists tasks to the durable queue; the
  web dyno either drains inline (`RUN_INLINE_WORKER=true`, default/single-service)
  or only enqueues while a dedicated worker executes (`RUN_INLINE_WORKER=false`).
  `render.yaml` declares web + worker + managed Postgres.
- **Diagnostics** now shows worker mode and live queue depth
  (`queued/claimed/done/failed`) alongside the existing configured-vs-verified
  provider/B2 health.
- **Regression + innovation test suites** added: worker queue, provider-error
  taxonomy, FSM same-state regression, and the innovation/generalisation/
  counterfactual/fixpoint proofs.
- **Executable evidence harnesses**: `scripts/benchmark.py`,
  `scripts/b2_proof.py`, `scripts/pg_claim_proof.py`.

The pre-existing engine (ChangeSet, propagation, evidence, MinimalRepairPlanner,
FSM, services, official Genblaze SDK integration, B2 backend, presigned URLs)
was **preserved, not rewritten**.

## What was actually tested — exact results
```
ruff check rusted_recall tests              → All checks passed
mypy rusted_recall                          → Success: no issues found in 43 source files
pytest (sqlite, local storage, no keys)     → 165 passed, 2 skipped
alembic upgrade head on Postgres 16         → initial → 15fabd319801 → 2b7c9d1e4f10 → 3c8e2f5a9b21 OK (down/up re-verified)
tests/test_opportunity.py                   → 8 passed (discover, execute+B2 proof, idempotent re-scan,
                                               refuse blocked, causal + counterfactual rejection,
                                               generative blocked vs verified)
scripts/pg_claim_proof.py (real Postgres)   → items=5 successful_claims=5 unique=5 threads=10 → PASS
scripts/b2_proof.py (real B2 bucket)        → evidence/B2_PROOF.json result: PASS
scripts/benchmark.py                        → evidence/BENCHMARK_RESULTS.json
```
Full capability matrix with per-test citations: `evidence/HACKATHON_MATRIX.md`.

## What is deployed
- Public HTTPS web + managed Postgres + B2 are live on Render. PR #11
  (Verified Opportunity + preflight + UX) is **merged and deployed** — the
  preflight capability row is live on `https://rusted-recall.onrender.com/diagnostics`
  and the deploy runs `alembic upgrade head` (so `3c8e2f5a9b21` is applied
  automatically). The dedicated worker service is defined in `render.yaml`
  but **not yet applied** as a Render Blueprint (web drains inline today).
- The `derivation_method` UI selector is in the follow-up branch and deploys on
  merge of its PR.

## Worker configuration status
- Code: **correct and tested** (durable persistence, atomic claim on real
  Postgres, stale recovery, restart + duplicate safety, honest failure).
- Deployment: **not yet a separate Render service.** Today the single web dyno
  drains its own durable queue inline (functional). To run a dedicated worker,
  apply `render.yaml` and set web `RUN_INLINE_WORKER=false`.

## Remaining blockers
1. **GMI credits** — real Seedream generation returns HTTP 402 "Insufficient
   credits". Blocks real generation + Golden/Unseen production recalls only.
2. **Deploy this branch** (merge PR) + optionally apply `render.yaml` for the
   dedicated worker.
3. **Rotate** the B2/GMI/OpenAI keys pasted in chat — treat as compromised.

## Exact owner actions
1. Add credits at https://console.gmicloud.ai (Billing).
2. Rotate B2/GMI/OpenAI keys.
3. Merge the PR (redeploys web); optionally apply `render.yaml` as a Blueprint
   and set web `RUN_INLINE_WORKER=false`.

## The single paid end-to-end test to run later
On `https://rusted-recall.onrender.com`: Run Live Recall → Approve → Repair a
`GENERATIVE_REPAIR` asset, then confirm on `/diagnostics` + `/submission-evidence`:
provider "verified working", a `GenerationRun` with a real upstream request id +
genblaze versions, a new immutable `AssetVersion` (origin=repaired) with B2
read-back SHA match, manifest + lineage + audit event, and original preserved.

## Evidence pack index
`FINAL_DELIVERY_REPORT.md` · `HACKATHON_MATRIX.md` · `INNOVATION_PROOF.md` ·
`GENERALISATION_PROOF.md` · `COUNTERFACTUAL_PLANNING_PROOF.md` ·
`FIXPOINT_IDEMPOTENCE_PROOF.md` · `GENBLAZE_PROOF.md` · `B2_PROOF.md` +
`B2_PROOF.json` · `BENCHMARK_RESULTS.json` · `PRODUCTION_JOURNEY_PROOF.md` ·
`GOLDEN_RUN_PROOF.md`
