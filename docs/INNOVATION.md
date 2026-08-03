

## 1. The ChangeSet (`rusted_recall/changeset.py`)

A change to a source of truth is modelled as a typed `ChangeSet` — an ordered list of
`ChangeOperation`s (`replace_text`, `replace_visual_reference`, `claim_withdrawal`,
`price_change`, `person_removal`, `voice_expiry`, …). Each operation knows two things
the rest of the system needs:

- **`requires_generative_repair`** — whether fixing it needs a pixel/audio regeneration
  or just a deterministic text overlay.
- **`propagates_through(edge_type)`** — which dependency relationships it can travel along.

A pure text claim change does **not** propagate along a visual-similarity edge; a logo
swap does. This is the difference between "re-checking everything" and "re-checking what
can actually be affected."

Change understanding can also be **inferred** (`propose_changeset`): exact text diffs are
certain (`confidence = 1.0`), while perceptual-hash-derived visual changes are flagged
`inferred=True` with graded confidence from the pHash distance — the system never pretends
an inferred computer-vision result is a certainty.

## 2. The Change Propagation Engine (`rusted_recall/propagation.py`)

Given a `ChangeSet`, a dependency graph snapshot, and distribution state, the engine
computes an `ImpactSet`. It:

- traverses **only** edge types the ChangeSet's operations can propagate through;
- always honours explicit / manifest / parent-child structural edges;
- is cycle-safe and depth-capped, with confidence decay and independent-path combination;
- classifies each asset with the explainable weighted score
  (structural, visual, text, semantic, derivation, human) × market applicability ×
  active-distribution factor;
- emits a **causal explanation** (the dependency chain and edge types) and a
  **propagation reason** for every affected asset — no black-box scores.

## 3. The Minimal Repair Planner (`rusted_recall/planner.py`)

The naive approach regenerates every affected asset. The planner instead recognises that
crop/resize children are **deterministic functions** of a master. It repairs the master
once and rebuilds children deterministically, then reports the *calculated* savings:
`naive_generative_operations`, `generative_operations`, `deterministic_rebuilds`, and
`operations_avoided`, plus an execution DAG. The saving is computed from the real graph,
never hardcoded.

## 4. Immutable provenance in Backblaze B2

Every original is written once and never overwritten; every repair produces a new
immutable `AssetVersion` with a manifest linking it to the source version, the ChangeSet,
the provider/model, and validation results. The recall report is reconstructable purely
from B2 objects and the append-only audit log.

## Why this is defensible

The moat is not "we call an image model." It is the **typed change semantics + evidence
graph + minimal-repair calculation + immutable provenance** working together, so that
"when the source changes, know exactly what media must change with it" is a computed,
auditable answer rather than a guess.
