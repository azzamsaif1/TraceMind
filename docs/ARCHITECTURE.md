# Architecture

Rusted Recall detects when a source-of-truth element changes, finds every
affected media asset with explainable evidence, repairs affected assets through
a real generative-media pipeline, preserves prior versions immutably, and emits
an auditable recall report.

## Component diagram

```mermaid
flowchart TB
    Browser["Browser UI (FastAPI + Jinja)"]

    subgraph App["Rusted Recall application"]
        Web["web/app.py — screens, health, diagnostics, report downloads"]
        Services["services.py — ingestion, analysis, impact, review, repair, reporting"]
        Jobs["jobs.py — background repair worker"]
        subgraph Engines["Domain engines"]
            Hashing["hashing (sha256 + phash)"]
            Evidence["evidence engine"]
            Graph["dependency graph"]
            Scoring["impact scoring"]
            Recall["recall state machine"]
            Repair["repair plans + idempotency"]
            Validation["output validation"]
            Manifest["manifests + reporting"]
        end
        Providers["providers — GMI Cloud + Genblaze pipeline"]
        Storage["storage — B2 (S3) / local dev"]
    end

    DB[("PostgreSQL")]
    B2[("Backblaze B2")]
    GMI["GMI Cloud image API"]
    Genblaze["Genblaze pipeline"]

    Browser --> Web
    Web --> Services
    Web --> Jobs
    Services --> Engines
    Services --> Providers
    Services --> Storage
    Jobs --> Services
    Services --> DB
    Storage --> B2
    Providers --> Genblaze
    Genblaze --> GMI
```

## Recall lifecycle

```mermaid
sequenceDiagram
    actor User
    participant UI
    participant Services
    participant Graph
    participant Scoring
    participant Jobs
    participant Genblaze
    participant B2

    User->>UI: Create recall (old → new source version)
    UI->>Services: create_recall_event + run_impact_analysis
    Services->>Graph: traverse dependency edges from changed source
    Graph-->>Services: strongest paths per asset
    Services->>Scoring: weighted evidence → classification
    Scoring-->>Services: directly/probably/needs_review/safe + reasons
    Services-->>UI: impact map + review queue (status: ready_for_review)
    User->>UI: Run repairs
    UI->>Jobs: enqueue repair task
    Jobs->>Services: build plan (stored) → execute
    Services->>Genblaze: pipeline.run(request)
    Genblaze->>GMI: image edit/generation
    GMI-->>Genblaze: output bytes
    Genblaze-->>Services: result
    Services->>Services: validate output
    Services->>B2: store immutable repaired version + manifest
    Services-->>UI: before/after + audit report (status: completed)
```

## State machine (recall status)

`draft → analysing → ready_for_review → approved → repairing →
partially_completed | completed`, with `failed` and `cancelled` as alternate
terminals. Transitions are enforced in `rusted_recall/recall.py`; illegal
transitions raise.

## Scoring (directive section 12)

```
evidence_score = 0.30·structural + 0.20·visual + 0.15·text
               + 0.15·semantic + 0.10·derivation + 0.10·human_confirmation
impact_score   = evidence_score · market_applicability · active_distribution
```

Thresholds: `directly_affected ≥ 0.80`, `probably_affected ≥ 0.55`,
`needs_review ≥ 0.25`, else `safe`. A confirmed explicit dependency overrides to
`directly_affected`; conflicting evidence forces `needs_review`. Weights and
thresholds live in `config.py` and are shown on `/diagnostics`.

## Why FastAPI (not Streamlit)

The required screens need an interactive impact-map graph, real background job
state with polling, streamed object serving, and multi-format report downloads.
A FastAPI app with server-rendered templates delivers these reliably in one
coherent product, replacing the original Streamlit prototype and its off-scope
modes.

## Trust boundaries

- **No provider → no output.** Repairs are disabled and reported; nothing is
  fabricated.
- **No B2 in production → hard failure.** Local storage is dev-only.
- Test-only deterministic providers live under `tests/` and are never imported
  by the application.
