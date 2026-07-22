# Rusted Recall — Devpost submission

**Tagline:** Change-impact intelligence and automated recall for generative media.

## Inspiration

Brands and studios reuse the same package, logo, claim, price, and licensed
likeness across hundreds of derived assets. When the source of truth changes —
a reformulated product, a regulatory claim change, an expired license — teams
scramble to find and fix every downstream asset by hand, with no audit trail.
We wanted the "git blame + recall" for generative media: given a change, show
exactly what's affected, *why*, fix it, and prove what happened.

## What it does

Rusted Recall registers **source-of-truth items** and ingests **media assets**,
computing real SHA-256 and perceptual hashes and storing originals immutably in
Backblaze B2. A multimodal **evidence engine** links assets to sources (explicit
declaration, hash duplicate, perceptual derivative, OCR text match, semantic and
visual similarity, parent-child derivation). When you declare a change, it
traverses the dependency graph and produces an **explainable impact score** that
classifies each asset as directly affected / probably affected / needs review /
safe — showing the component weights, reasons, and the dependency path. Affected
assets are **repaired** through a Genblaze + GMI Cloud pipeline as durable jobs;
outputs are validated and stored as **new immutable versions** with manifests,
and the whole event exports as an auditable JSON/CSV/HTML/PDF report.

## How we built it

- **Backblaze B2** (S3-compatible API via boto3) for all object storage, with
  hash metadata and read-back verification; originals are never overwritten.
- **Genblaze** pipeline orchestration wrapping **GMI Cloud** image
  generation/editing for repairs.
- **FastAPI** + server-rendered UI with an interactive impact map, live job
  polling, and report downloads.
- **PostgreSQL** + SQLAlchemy + Alembic for a typed domain model with immutable
  asset versions and an append-only audit log.
- A pure-Python domain core (hashing, evidence, graph, scoring, recall state
  machine, repair planning, validation, reporting) covered by unit + E2E tests.

## Challenges we ran into

- Making impact **explainable** rather than a black-box score — we persist every
  evidence edge and the weighted components behind each classification.
- Keeping the demo **honest**: when no provider is configured, repairs are
  disabled and clearly labelled instead of showing fake "after" images.
- Enforcing **immutability and lineage** end-to-end so every visible result
  traces to a real stored object and audit event.

## Accomplishments we're proud of

A real, tested vertical slice: upload → hash → store in B2 → link to source →
recall → explainable impact → repair via the pipeline → immutable new version +
manifest → auditable report — with the same code paths driving the demo seed.

## What we learned

Provenance and reversibility are the hard parts of generative media at scale;
the storage/versioning/audit design matters more than the model call.

## What's next

Video/audio asset repair, deeper semantic embeddings, multi-provider fallback,
and an external job queue for horizontal scale.

## Built with

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Backblaze B2 (S3 API), Genblaze,
GMI Cloud, Pillow, imagehash, boto3, ReportLab, Docker.
