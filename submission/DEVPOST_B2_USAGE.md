# How we use Backblaze B2

B2 is the media system of record for the entire product — not a demo afterthought.

Stored in B2 (via the S3-compatible API, boto3, with retry/backoff and read-back
verification): source references, customer originals, previews, analysis artifacts,
generation manifests, repaired/generated media, dependency-graph snapshots, repair plans,
and recall reports/export packages.

Guarantees:
- **Originals are never overwritten** — every repair is a new immutable object/version.
- Each write records content-type, length, and SHA-256 metadata and is verified by read-back.
- A tenant-aware key namespace isolates organisations and workspaces.
- The full recall report is reconstructable from B2 objects + the append-only audit log.
- Buckets are private; time-limited signed URLs are used for reads.
