"""Repair-plan construction, idempotency keys, and provider error classification
(directive section 13)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

# Failure categories (directive section 13 "retry policy").
ERR_AUTH = "authentication"
ERR_QUOTA = "quota"
ERR_RATE_LIMIT = "rate_limit"
ERR_TIMEOUT = "timeout"
ERR_UNAVAILABLE = "provider_unavailable"
ERR_INVALID = "invalid_request"
ERR_SAFETY = "safety_rejection"
ERR_CORRUPT = "corrupt_response"
ERR_STORAGE = "storage_failure"
ERR_VALIDATION = "validation_failure"

# Which categories are worth retrying.
RETRYABLE = {ERR_RATE_LIMIT, ERR_TIMEOUT, ERR_UNAVAILABLE, ERR_STORAGE, ERR_CORRUPT}
# Permanent failures that must never be retried endlessly.
NON_RETRYABLE = {ERR_AUTH, ERR_INVALID, ERR_SAFETY, ERR_QUOTA, ERR_VALIDATION}


def is_retryable(category: str) -> bool:
    return category in RETRYABLE


@dataclass
class RepairPlan:
    """Deterministic, asset-specific repair plan stored before execution."""

    asset_id: str
    asset_version_id: str
    recall_event_id: str
    changed_element: str
    editing_method: str
    provider: str
    model: str
    operation_spec: dict
    reference_inputs: list[str]
    expected_dimensions: tuple[int, int] | None
    validation_checks: list[str]
    fallback_provider: str | None
    retry_policy: dict
    output_b2_key: str
    estimated_cost: float | None = None
    plan_version: int = 1
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            self.idempotency_key = compute_idempotency_key(
                recall_event_id=self.recall_event_id,
                asset_version_id=self.asset_version_id,
                plan_version=self.plan_version,
                provider=self.provider,
                model=self.model,
                operation_parameters=self.operation_spec,
            )

    def as_dict(self) -> dict:
        d = asdict(self)
        if self.expected_dimensions is not None:
            d["expected_dimensions"] = list(self.expected_dimensions)
        return d


def compute_idempotency_key(
    *,
    recall_event_id: str,
    asset_version_id: str,
    plan_version: int,
    provider: str,
    model: str,
    operation_parameters: dict,
) -> str:
    """Stable idempotency key (directive section 13 "idempotency").

    Repeated execution with identical inputs yields the same key so duplicate
    generations are controlled.
    """
    params_hash = hashlib.sha256(
        json.dumps(operation_parameters, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    material = "|".join(
        [recall_event_id, asset_version_id, str(plan_version), provider, model, params_hash]
    )
    return hashlib.sha256(material.encode()).hexdigest()


def build_repair_instruction(
    *,
    asset_type: str,
    asset_description: str,
    old_reference: str,
    new_reference: str,
    market: str,
    preservation_constraints: list[str] | None = None,
    approved_instructions: str = "",
) -> str:
    """Build an asset-specific repair instruction (never one generic prompt for
    every asset — directive section 13)."""
    constraints = preservation_constraints or [
        "preserve composition and layout",
        "preserve background and lighting",
        "change only the packaging/claim element",
    ]
    lines = [
        f"Asset type: {asset_type}.",
        f"Asset description: {asset_description}.",
        f"Replace the old element ('{old_reference}') with the new element ('{new_reference}').",
        f"Applicable market: {market}.",
        "Preservation constraints: " + "; ".join(constraints) + ".",
    ]
    if approved_instructions:
        lines.append(f"Reviewer instructions: {approved_instructions}.")
    return " ".join(lines)


DEFAULT_RETRY_POLICY = {"max_attempts": 3, "base_delay_seconds": 1.0, "backoff": "exponential"}
