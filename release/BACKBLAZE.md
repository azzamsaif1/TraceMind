# Backblaze B2 setup

B2 is the media system of record: source references, originals, previews, analysis,
manifests, repaired media, graph snapshots, repair plans, and recall reports. **Originals
are never overwritten.**

## Create a bucket + key

1. Create a **private** bucket (never public-write) in Backblaze B2.
2. Create an **application key scoped to that bucket** (least privilege: read/write on the
   one bucket only).
3. Note the S3-compatible endpoint and region for the bucket.

## Configure

```bash
STORAGE_BACKEND=b2
B2_KEY_ID=your-key-id
B2_APP_KEY=your-application-key
B2_BUCKET_NAME=your-bucket
B2_ENDPOINT_URL=https://s3.<region>.backblazeb2.com
B2_REGION=<region>
```

Rusted Recall uses the S3-compatible API (boto3) with retry/backoff, content-type/length/
hash metadata, and read-back verification after every write.

## Object namespace

Objects are keyed under a tenant-aware prefix so organisations and workspaces are isolated.
See `docs/DATA_MODEL.md` for the full layout.

## Security

- Bucket must be private; signed URLs are used for time-limited reads.
- Rotate keys periodically. If a key is ever committed, revoke it immediately.
