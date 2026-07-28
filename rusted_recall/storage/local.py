"""Development-only local filesystem storage backend.

This backend is never used in production (directive section 2.3). It mirrors the
same object-key namespace on disk so the rest of the application is unchanged,
and it is always clearly labelled as development storage in the UI/diagnostics.
"""
from __future__ import annotations

import json
from pathlib import Path

from rusted_recall.config import Settings
from rusted_recall.hashing import sha256_bytes
from rusted_recall.logging_setup import get_logger
from rusted_recall.storage.base import (
    ObjectNotFoundError,
    ReadBackVerificationError,
    StorageBackend,
    StorageError,
    StoredObject,
)

logger = get_logger(__name__)


class LocalStorage(StorageBackend):
    backend_name = "local-dev"
    is_system_of_record = False

    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.local_storage_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent traversal outside the storage root.
        target = (self._root / key).resolve()
        if not str(target).startswith(str(self._root)):
            raise ValueError(f"illegal object key: {key}")
        return target

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = None,
        verify_read_back: bool = True,
    ) -> StoredObject:
        digest = sha256_bytes(data)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        meta = {"sha256": digest, "content-type": content_type, "content-length": str(len(data))}
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})
        path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta))
        if verify_read_back and sha256_bytes(path.read_bytes()) != digest:
            raise ReadBackVerificationError(f"read-back hash mismatch for {key}")
        logger.info("local object stored", extra={"b2_key": key, "content_length": len(data)})
        return StoredObject(
            key=key, size=len(data), content_type=content_type, sha256=digest, metadata=meta
        )

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise ObjectNotFoundError(key)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        search_root = base if base.is_dir() else base.parent
        results: list[str] = []
        if not search_root.exists():
            return results
        for p in search_root.rglob("*"):
            if p.is_file() and not p.name.endswith(".meta.json"):
                rel = p.relative_to(self._root).as_posix()
                if rel.startswith(prefix):
                    results.append(rel)
        return sorted(results)

    def health_check(self) -> bool:
        return self._root.exists()
