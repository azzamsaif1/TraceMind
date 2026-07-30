# B2 Proof (live, no paid provider call)

**Claim:** Backblaze B2 is the durable system of record — real write, real
read-back, SHA-256 verification, immutable new versions (no overwrite), and
short-lived presigned reads. Local storage is never presented as B2 evidence.

Reproduce (requires `B2_*` configured):
```bash
python -m scripts.b2_proof   # writes evidence/B2_PROOF.json
```

The script refuses to run unless `STORAGE_BACKEND=b2` resolves to a real
`B2Storage` — a local backend raises `SystemExit`, so this artifact can only be
produced against real B2.

## Result — `result: PASS` (see `evidence/B2_PROOF.json`)
Bucket `Tracemind-storage`, endpoint `s3.eu-central-003.backblazeb2.com`. All
checks true:

| Check | Result |
|---|---|
| original write → read-back SHA-256 match | true |
| repaired new-version write → read-back SHA-256 match | true |
| original unchanged after new version written | true |
| distinct object keys (no overwrite) | true |
| short-lived presigned GET returns identical bytes | true |

Two immutable objects were written under a timestamped `_proof/b2/...` prefix
(an `original.png` and a separate `repaired_v2.png`), proving the
write→read-back→hash→no-overwrite→presigned path end to end.

## In the production repair path
`services.execute_repair_job` uses the same backend to: read the original,
create short-lived presigned reference URLs for the provider (bucket stays
private, URLs never persisted/displayed), store the generated output under a NEW
key, read back + hash, build a provenance manifest, and create an immutable
`AssetVersion` + lineage + audit event. `B2Storage.put_bytes` verifies read-back
by default (`ReadBackVerificationError` on mismatch).
