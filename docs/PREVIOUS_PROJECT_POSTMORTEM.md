# Postmortem: the original TraceMind prototype

This documents what the repository was before Rusted Recall, so the same mistakes are not
repeated. It complements `docs/EXISTING_SYSTEM_AUDIT.md`.

## What the prototype claimed vs. what it did

The prototype presented itself as an AI media pipeline, but the core "generation" step in
`orchestrator.py` (lines 38-47) **drew text onto a blank PIL image** and returned it as if
it were model output. Several "modes" (Opportunity Mode, Failure Mode, adaptive prompting,
evolution/feedback engines, `generate_project.py`, `generate_all.py`, `another.py`) were
scaffolding with no real backing operation.

## Root causes

1. **Demo-first architecture.** Visible results were produced by demo code paths, not by
   the same code a real user would run. There was no way to tell a real result from a
   staged one.
2. **No system of record.** No database, no immutable versioning, no audit log — nothing
   could be reconstructed or trusted after the fact.
3. **No honest failure mode.** When an integration was missing, the UI still showed
   "success" using fabricated output.
4. **Secrets in the repo.** Real-looking B2 and GMI credentials were committed to
   `.env.example` and remain in git history (see below).

## What we kept

Genuinely real pieces were preserved and hardened: SHA-256 + perceptual hashing, real B2
upload/download (moved to an S3-compatible client with read-back verification), and the
idea of a media-provenance product.

## Corrective principles (now enforced — see ANTI_REGRESSION_GATES.md)

- The demo runs the **same** production ingestion/analysis/repair services as a real user;
  no demo-only application logic.
- Every visible number traces to a real operation (hash, B2 object, provider call,
  computed score).
- Missing integrations fail honestly and disable the operation; they never fabricate.
- Immutable versions + append-only audit make every result reconstructable.

## Outstanding security debt (owner action required)

The leaked credentials are present in commits `001130e`, `ba6e9f8`, `2aed6b3`. `.env.example`
is sanitized and `.gitignore` hardened, but **the owner must rotate/revoke the B2 and GMI
Cloud credentials**, and separately decide whether to authorize a destructive git-history
scrub.
