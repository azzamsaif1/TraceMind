"""Live B2 write / read-back / hash / original-preservation proof
(FINAL DELIVERY §8, §19.7, §19.12, §19.13).

This performs REAL Backblaze B2 operations against the configured bucket. It
does NOT make any paid provider (GMI/Seedream) call. It writes two immutable
objects (an 'original' and a 'repaired' new version), reads them back, verifies
SHA-256 matches on read-back, verifies the original is byte-for-byte unchanged
after the new version is written, and exercises a short-lived presigned GET.

Emits evidence/B2_PROOF.json with object keys + hashes (no credentials, no
permanent URLs).

Usage (requires B2_* configured in the environment / .env):
    python -m scripts.b2_proof
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from rusted_recall.config import get_settings
from rusted_recall.storage import get_storage
from rusted_recall.storage.b2 import B2Storage


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _img(color) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (96, 96), color=color).save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    settings = get_settings()
    storage = get_storage(settings)
    if not isinstance(storage, B2Storage):
        raise SystemExit(
            "STORAGE_BACKEND is not B2. Set STORAGE_BACKEND=b2 and B2_* to run the "
            "live B2 proof (local storage must never be presented as B2 evidence)."
        )

    run = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix = f"_proof/b2/{run}"
    original = _img((10, 130, 60))
    repaired = _img((200, 60, 40))
    original_key = f"{prefix}/original.png"
    repaired_key = f"{prefix}/repaired_v2.png"

    # 1. WRITE original (with built-in read-back verification).
    o_stored = storage.put_bytes(original_key, original, "image/png", metadata={"role": "original"})
    # 2. READ BACK + hash verify.
    o_read = storage.get_bytes(original_key)
    original_readback_ok = _sha(o_read) == _sha(original) == o_stored.sha256

    # 3. WRITE a NEW immutable version under a DIFFERENT key (no overwrite).
    r_stored = storage.put_bytes(repaired_key, repaired, "image/png", metadata={"role": "repaired"})
    r_read = storage.get_bytes(repaired_key)
    repaired_readback_ok = _sha(r_read) == _sha(repaired) == r_stored.sha256

    # 4. ORIGINAL PRESERVED: re-read original after writing the new version.
    o_again = storage.get_bytes(original_key)
    original_unchanged = _sha(o_again) == _sha(original)

    # 5. Short-lived presigned GET works and returns the same bytes.
    url = storage.create_presigned_get_url(original_key, 300)
    presigned_bytes = httpx.get(url, timeout=30.0).content
    presigned_ok = _sha(presigned_bytes) == _sha(original)

    artifact = {
        "generated_at": run,
        "backend": "backblaze-b2",
        "bucket": settings.b2_bucket_name,
        "endpoint": settings.b2_s3_endpoint,
        "objects": {
            "original": {"key": original_key, "sha256": o_stored.sha256, "bytes": len(original)},
            "repaired_new_version": {"key": repaired_key, "sha256": r_stored.sha256, "bytes": len(repaired)},
        },
        "checks": {
            "original_write_readback_hash_match": original_readback_ok,
            "repaired_write_readback_hash_match": repaired_readback_ok,
            "original_unchanged_after_new_version": original_unchanged,
            "distinct_object_keys_no_overwrite": original_key != repaired_key,
            "presigned_get_returns_same_bytes": presigned_ok,
        },
        "note": "No provider/paid call performed. Presigned URL omitted (short-lived, private).",
    }
    all_ok = all(artifact["checks"].values())
    artifact["result"] = "PASS" if all_ok else "FAIL"

    out = Path("evidence/B2_PROOF.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2))
    print(json.dumps(artifact, indent=2))
    print(f"\nwrote {out}")
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
