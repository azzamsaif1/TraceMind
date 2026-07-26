# What it does

- Ingests media, computing SHA-256 + perceptual hashes and extracting text; stores originals
  immutably in Backblaze B2 (never overwritten).
- Builds a multimodal dependency graph (explicit declaration, prompt/manifest, SHA-256
  duplicate, perceptual-hash derivative, OCR text, semantic and visual similarity,
  parent-child derivation), storing full evidence per edge.
- Models source changes as typed ChangeSets and propagates them with a cycle-safe,
  depth-capped engine that respects change semantics.
- Classifies impact (directly/probably affected, needs review, safe) with an explainable
  score and a causal explanation per asset.
- Plans a minimal repair set, reporting calculated operations avoided.
- Executes real repairs via Genblaze + GMI Cloud; stores new immutable versions + manifests.
- Exports auditable reports (JSON/CSV/HTML/PDF).
- Ships as a multi-tenant SaaS: signup/login, organisations, workspaces, tenant isolation,
  onboarding, usage metering, and account/usage views.
