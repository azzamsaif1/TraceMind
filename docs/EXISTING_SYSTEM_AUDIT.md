# Existing System Audit

_Audit of the repository at branch point (last commit `2aed6b3`), performed before the Rusted Recall rebuild. Purpose: guide implementation, not to be exhaustive._

## Summary

The repository was a Streamlit "Trusted Decision OS" prototype: generate an image from a
prompt, hash it, upload to Backblaze B2, and store a manifest. The **image generation is
mocked** (draws text on a blank PIL canvas), and several bolted-on "self-improving AI"
modules are unrelated to the Rusted Recall product. The genuinely reusable parts are the
cryptographic/perceptual hashing and the basic B2 client.

## What works (keep / strengthen)

| Area | File | Notes |
|------|------|-------|
| SHA-256 hashing | `verification.py::calculate_sha256` | Correct streaming hash. Reusable as-is. |
| Perceptual hashing | `verification.py::calculate_perceptual_hash` | Real `imagehash.phash`. Reusable; extend with Hamming distance. |
| B2 upload/download | `utils.py` | Real `b2sdk` calls. Works but needs refactor: no retry/backoff, no read-back verification, no content-type/length/hash metadata, re-authorizes on every call, public-URL builder is a hardcoded S3 host. |
| Manifest persistence | `provenance.py` | Real fsync-before-upload pattern; good durability instinct. Repurpose into repair/analysis manifests. |
| Decision listing | `memory.py` | Real B2 `ls`. Repurpose into asset/version listing. |

## What is fake (must be replaced with real operations)

- **Mocked image generation** — `orchestrator.py` lines 38-47: creates a blank
  `Image.new(...)` and draws the decision id / prompt text onto it. No provider is called.
  This is the core violation of directive §2.1 ("no simulation") and must be replaced by a
  real Genblaze/GMI pipeline.
- **"Adaptive wisdom" / scoring** — `feedback_engine.py` produces heuristic scores presented
  as analysis; not tied to any real model. Off-scope for Rusted Recall.

## What is missing (must be built)

- No Genblaze integration of any kind.
- No relational database, no typed domain models, no migrations.
- No durable/async job queue for long-running repairs.
- No dependency graph, evidence model, impact scoring, recall state machine, review queue,
  repair planning, validation, or reporting.
- No source-of-truth registry; no asset/version immutability; no append-only audit log.
- No health/readiness endpoints, structured logging, or diagnostics.
- No Dockerfile / docker-compose / deployment config.
- No tests. No CI.
- `utils.py` uses the native B2 API and a hardcoded S3-style public URL; directive §10
  prefers the S3-compatible API with a clear object namespace and read-back verification.

## What to remove (off-scope for the competition-facing product)

Per directive §5 ("remove Reddit Opportunity Mode, generic idea generation, features
unrelated to media recall"):

- `modes/opportunity_mode.py` (Reddit opportunity mode)
- `modes/failure_mode.py` (generic failure analysis)
- `adaptive_prompt_engine.py`
- `evolution_engine.py`
- `enhanced_feedback_engine.py`
- `feedback_engine.py` (heuristic "wisdom"; not part of recall)
- `multimodal_interface.py` (abstract no-op provider adapter presented as integration)
- `orchestrator.py`, `orchestrator_wrapper.py` (mock generation pipeline)
- `generate_project.py`, `generate_all.py`, `another.py` (scratch/demo scripts)
- `app.py` (old Streamlit UI) and `modes/memory_mode.py` — replaced by the new UI.
- `memory.py` — logic folded into the new asset registry service.

## Security concerns

- **Leaked credentials**: `.env.example` committed real-looking `B2_KEY_ID`, `B2_APP_KEY`,
  `B2_BUCKET_NAME`, and a `GMICLOUD_API_KEY` JWT. Present in history (commits `001130e`,
  `ba6e9f8`, `2aed6b3`). Sanitized in the working tree; **must be rotated by the owner** and
  history scrubbed (owner-authorized force-push).
- No environment validation; missing credentials would fail with opaque errors instead of a
  clear configuration error (directive §2.3).
- Public-URL builder assumes an unauthenticated public bucket.

## Dependencies

`streamlit, b2sdk, python-dotenv, Pillow, imagehash, requests`. No lock file, no pinned
transitive versions, no vulnerability scanning. The rebuild pins dependencies and adds a
lock strategy.

## Migration requirements

No existing database to migrate. Existing B2 objects (if any) live under a flat
`images/`, `decisions/`, `manifests/` layout; the new product uses the
`rusted-recall/workspaces/...` namespace (directive §10) and does not depend on old objects.
