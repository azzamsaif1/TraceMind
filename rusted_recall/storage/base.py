"""Storage backend protocol, object-key namespace, and error types."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

ROOT_PREFIX = "rusted-recall"


class StorageError(Exception):
    """Base class for storage errors."""


class StorageConfigError(StorageError):
    """Raised when the storage backend is not correctly configured."""


class ObjectNotFoundError(StorageError):
    """Raised when an object key does not exist."""


class ReadBackVerificationError(StorageError):
    """Raised when a written object cannot be read back with a matching hash."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    content_type: str
    sha256: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    """Sanitise a user-supplied filename to prevent path traversal / injection
    into object keys (directive section 16)."""
    name = name.replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip("._-") or "file"
    return name[:200]


class ObjectKeys:
    """Build the inspectable B2 object namespace from directive section 10.

    All keys are derived server-side from validated UUIDs and sanitised
    filenames; user input never controls arbitrary object keys.
    """

    def __init__(self, workspace_id: str) -> None:
        self.ws = f"{ROOT_PREFIX}/workspaces/{workspace_id}"

    # --- source of truth ---
    def sot_original(self, item_id: str, version_id: str, filename: str) -> str:
        return f"{self.ws}/source-of-truth/{item_id}/versions/{version_id}/original/{sanitize_filename(filename)}"

    def sot_metadata(self, item_id: str, version_id: str) -> str:
        return f"{self.ws}/source-of-truth/{item_id}/versions/{version_id}/metadata.json"

    # --- assets ---
    def asset_original(self, asset_id: str, version_id: str, filename: str) -> str:
        return f"{self.ws}/assets/{asset_id}/versions/{version_id}/original/{sanitize_filename(filename)}"

    def asset_preview(self, asset_id: str, version_id: str, filename: str) -> str:
        return f"{self.ws}/assets/{asset_id}/versions/{version_id}/preview/{sanitize_filename(filename)}"

    def asset_analysis(self, asset_id: str, version_id: str) -> str:
        return f"{self.ws}/assets/{asset_id}/versions/{version_id}/analysis/analysis.json"

    def asset_manifest(self, asset_id: str, version_id: str, manifest_id: str) -> str:
        return f"{self.ws}/assets/{asset_id}/versions/{version_id}/manifests/{manifest_id}.json"

    # --- recall events ---
    def recall_trigger(self, recall_id: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/trigger/trigger.json"

    def recall_impact(self, recall_id: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/impact/impact.json"

    def recall_plan(self, recall_id: str, plan_id: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/plans/{plan_id}.json"

    def recall_execution_manifest(self, recall_id: str, run_id: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/executions/{run_id}/manifest.json"

    def recall_execution_logs(self, recall_id: str, run_id: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/executions/{run_id}/logs.json"

    def recall_report(self, recall_id: str, fmt: str) -> str:
        return f"{self.ws}/recall-events/{recall_id}/reports/final-report.{fmt}"

    # --- repaired ---
    def repaired_output(self, asset_id: str, new_version_id: str, filename: str) -> str:
        return f"{self.ws}/repaired/{asset_id}/versions/{new_version_id}/output/{sanitize_filename(filename)}"

    def repaired_validation(self, asset_id: str, new_version_id: str) -> str:
        return f"{self.ws}/repaired/{asset_id}/versions/{new_version_id}/validation.json"

    def repaired_manifest(self, asset_id: str, new_version_id: str) -> str:
        return f"{self.ws}/repaired/{asset_id}/versions/{new_version_id}/manifest.json"

    # --- graph ---
    def graph_snapshot(self, timestamp: str) -> str:
        return f"{self.ws}/graph/snapshots/{sanitize_filename(timestamp)}.json"


@runtime_checkable
class StorageBackend(Protocol):
    """Minimal object storage contract used by the application."""

    backend_name: str
    is_system_of_record: bool

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str,
        metadata: dict[str, str] | None = ...,
        verify_read_back: bool = ...,
    ) -> StoredObject: ...

    def get_bytes(self, key: str) -> bytes: ...

    def create_presigned_get_url(self, key: str, expires_seconds: int = ...) -> str: ...

    def exists(self, key: str) -> bool: ...

    def list_prefix(self, prefix: str) -> list[str]: ...

    def presigned_get_url(self, key: str, expires_in: int = 900) -> str: ...

    def health_check(self) -> bool: ...
