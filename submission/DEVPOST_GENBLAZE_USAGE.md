# How we use Genblaze (and GMI Cloud)

Repairs are executed through the Genblaze pipeline boundary
(`rusted_recall/providers/genblaze.py`) with GMI Cloud as the real image
generation/editing provider.

- Each affected asset gets a deterministic, pre-stored repair plan (editing method,
  provider, model, operation spec, reference inputs, validation checks, retry policy,
  idempotency key) before any execution.
- The pipeline runs the plan against the provider, validates the output (dimensions, MIME,
  claim text presence/absence, perceptual drift), and stores a new immutable version +
  manifest in B2.
- If credentials are missing/invalid, jobs fail honestly (`authentication` /
  `provider_unavailable`); inputs and plans are preserved and **no fake output is produced**.
- Idempotency keys prevent double-generation on retries.
