"""Repair/generation manifest construction (directive sections 2.4, 9, 13).

A manifest links a repaired version back to its full provenance. Secrets are
never included.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

MANIFEST_SCHEMA_VERSION = "1.0.0"


def new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_repair_manifest(
    *,
    manifest_id: str | None = None,
    recall_event_id: str,
    source_of_truth_item_id: str,
    source_of_truth_version_id: str,
    original_asset_id: str,
    original_asset_version_id: str,
    original_sha256: str,
    original_b2_key: str,
    new_asset_version_id: str,
    output_sha256: str,
    output_b2_key: str,
    provider: str,
    model: str,
    genblaze_pipeline: str | None,
    operation_spec: dict,
    caused_by: str,
    validation: dict | None = None,
) -> dict:
    """Immutable manifest capturing every provenance link required by section 2.4."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": manifest_id or new_id(),
        "created_at": _now(),
        "recall_event_id": recall_event_id,
        "source_of_truth": {
            "item_id": source_of_truth_item_id,
            "version_id": source_of_truth_version_id,
        },
        "original_asset": {
            "asset_id": original_asset_id,
            "version_id": original_asset_version_id,
            "sha256": original_sha256,
            "b2_key": original_b2_key,
        },
        "repaired_asset": {
            "asset_id": original_asset_id,
            "new_version_id": new_asset_version_id,
            "sha256": output_sha256,
            "b2_key": output_b2_key,
        },
        "generation": {
            "provider": provider,
            "model": model,
            "genblaze_pipeline": genblaze_pipeline,
            "operation_spec": operation_spec,  # secrets excluded by construction
        },
        "caused_by": caused_by,
        "validation": validation or {},
    }
