# Golden / Unseen Production Recall — Status: BLOCKED (GMI credits)

A "Golden Production Recall" and an "Unseen Production Recall" both require a
**real generative execution** through Genblaze → GMI Seedream. That single step
is currently blocked because the GMI account returns **HTTP 402 "Insufficient
credits"** (verified live; classified `quota`). No paid call was made, per
explicit instruction.

Everything *around* the paid step is proven:
- ChangeSet → propagation → causal explanation → Minimal Repair → review are
  covered end-to-end for a **blind generic company** with no provider
  (`tests/test_innovation.py`), and for LumaLeaf/Northstar
  (`tests/test_generalisation.py`, `tests/test_end_to_end.py` with a
  deterministic local edit provider).
- B2 write/read-back/hash/no-overwrite/presigned is proven live
  (`evidence/B2_PROOF.json`).
- Immutable version + manifest + lineage + audit + validation are proven with
  the test provider (`tests/test_end_to_end.py`).

## The exact sequence to produce the Golden Run (once credits exist)
1. Ensure `GENBLAZE_ENABLED=true`, `GMICLOUD_API_KEY` set, `STORAGE_BACKEND=b2`,
   Postgres `DATABASE_URL`, and (recommended) the dedicated worker deployed.
2. On `https://rusted-recall.onrender.com`: **Run Live Recall** (LumaLeaf or
   Northstar) → **Approve** → **Repair** an asset whose plan is a
   `GENERATIVE_REPAIR`.
3. Verify on `/diagnostics` + `/submission-evidence`:
   - provider **verified working**; a `GenerationRun` with a real upstream
     request id + genblaze-core/gmicloud versions;
   - a new immutable `AssetVersion` (origin `repaired`) with B2 read-back SHA
     match; manifest + lineage + audit event present; original preserved.
4. Repeat via the **customer UI** for a brand-new, non-seeded campaign to
   capture the **Unseen Production Recall**.

Until step 2 succeeds with credits, this proof is honestly marked **BLOCKED** —
not complete.
