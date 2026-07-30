# Genblaze Proof (offline / preflight — no paid call)

**Claim:** real generative repairs execute through the pinned **official**
Genblaze runtime, not local orchestration; provenance is real; and no output is
ever fabricated. The one remaining step (an actual paid generation) is BLOCKED
on GMI credits.

## Pinned upstream runtime
```
genblaze-core==0.3.8
genblaze-gmicloud==0.3.5
```
Verified installed:
```
$ python -c "import importlib.metadata as m; print(m.version('genblaze-core'), m.version('genblaze-gmicloud'))"
0.3.8 0.3.5
```

## Adapter behaviour (tested, mocked upstream)
`rusted_recall/providers/genblaze_official.py` (`OfficialGenblazeImageProvider`):
- Selected by the factory when `GENBLAZE_ENABLED=true` and the SDK is importable; otherwise the direct GMI adapter. Same contract.
- Builds an official `Step`: `StepType.EDIT` when presigned reference URLs exist, else `StepType.GENERATE`.
- Passes reference URLs as upstream `Asset` inputs; sets Seedream params (size, format, watermark=false).
- Handles a returned **failed `Step`** and raised provider errors.
- Rejects missing/empty media URLs (`corrupt_response`).
- Downloads the real produced asset and maps upstream provenance (genblaze-core / connector versions, upstream request id) into the Rusted manifest.
- `tests/test_genblaze_official.py`

## Provider error taxonomy
`tests/test_provider_errors.py` + `tests/test_gmicloud.py` cover 401/403 auth,
402 quota, 404/400/422 invalid, 429 rate limit, 451 safety, 408/504 timeout,
5xx retryable-unavailable, malformed/missing-URL corrupt_response, and the
retryable-vs-permanent contract. Regression: a concrete `server_error` stays
retryable even if its message contains "invalid"/"not found" (PR #7).

## Live preflight (real HTTP, no credits consumed)
The official path reaches the live GMI request queue and returns
**HTTP 402 "Insufficient credits"**, correctly classified as `quota`
(permanent, not retried). This is an external credit blocker, not an adapter
fault.

## BLOCKED — the single paid step
Add credits at https://console.gmicloud.ai (Billing). Then the real
generation, output validation, and Golden/Unseen production recalls can run
(see `GOLDEN_RUN_PROOF.md`).
