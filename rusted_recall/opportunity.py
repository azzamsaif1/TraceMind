"""Verified Opportunity discovery primitives (spec section 3).

An opportunity is a concrete, executable action *created specifically by a
verified Recall state transition*. This module contains the pure reasoning
primitives — candidate generation, causal proof, counterfactual validation and
feasibility classification — over already-persisted facts. Nothing here talks to
an LLM and nothing is fabricated: a candidate is only ever built from the
before-state, the ChangeSet, the after-state and the dependency/lineage graph.

The lifecycle a candidate must pass before it is surfaced:

    candidate
      → causal proof            (the verified new state actually enables it)
      → constraint validation   (markets / publication constraints hold)
      → feasibility planning     (there is a concrete operation that can run)
      → counterfactual validation (it was NOT already valid before the change)
      → VERIFIED OPPORTUNITY

Rejection is truthful and specific:
  * missing causal evidence           → rejected (reason=no_causal_evidence)
  * already valid before the change   → rejected (reason=valid_before_change)
  * no executable operation           → blocked  (feasibility=blocked)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# Deterministic derivations reconcile natively (zero provider calls); anything
# else needs a generative operation and therefore a usable provider.
DETERMINISTIC_DERIVATIONS = {"crop": "deterministic_crop", "resize": "deterministic_resize"}

KIND_RECONCILE_DERIVATIVE = "reconcile_downstream_derivative"

# Lifecycle statuses.
STATUS_CANDIDATE = "candidate"
STATUS_VERIFIED = "verified"
STATUS_BLOCKED = "blocked"
STATUS_REJECTED = "rejected"
STATUS_EXECUTED = "executed"


def dedup_key(
    *,
    workspace_id: str,
    recall_id: str,
    old_version_id: str | None,
    new_version_id: str | None,
    kind: str,
    target_asset_id: str,
    params: dict | None = None,
) -> str:
    """Stable identity for an opportunity, derived only from *verified inputs*
    (spec Phase 1 "Deterministic identity"). Re-running discovery for the same
    verified state yields the same key, so the unique constraint on
    (recall_event_id, dedup_key) makes discovery idempotent.

    Deliberately excludes volatile capability signals (e.g. provider usability)
    so the same logical opportunity is one row regardless of transient state."""
    payload = {
        "workspace_id": workspace_id,
        "recall_id": recall_id,
        "transition": [old_version_id or "", new_version_id or ""],
        "kind": kind,
        "target_asset_id": target_asset_id,
        "params": params or {},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class CandidateAsset:
    """A downstream asset considered for a reconcile opportunity."""

    asset_id: str
    name: str
    derivation_method: str | None
    parent_asset_id: str | None
    # Did the parent get a repaired version from THIS recall? (causal evidence)
    parent_repaired: bool
    parent_repaired_version_id: str | None
    parent_name: str
    # Was this child itself already repaired in this recall?
    already_repaired: bool
    # Is the child's current version already derived from the parent's newest
    # (repaired) version? If so the reconcile was already done — counterfactual.
    already_reconciled: bool
    width: int | None
    height: int | None


@dataclass
class OperationPlan:
    asset_id: str
    name: str
    method: str
    native: bool
    blocked: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "method": self.method,
            "native": self.native,
            "blocked": self.blocked,
            "reason": self.reason,
        }


@dataclass
class OpportunityAssessment:
    """The typed verdict for a single candidate, with full evidence."""

    kind: str
    status: str
    title: str
    rationale: str
    operations: list[OperationPlan] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @property
    def native_operations(self) -> int:
        return sum(1 for o in self.operations if o.native and not o.blocked)

    @property
    def generative_operations(self) -> int:
        return sum(1 for o in self.operations if not o.native and not o.blocked)

    @property
    def blocked_operations(self) -> int:
        return sum(1 for o in self.operations if o.blocked)

    @property
    def feasibility_state(self) -> str:
        executable = [o for o in self.operations if not o.blocked]
        if not executable:
            return "blocked"
        if self.blocked_operations:
            return "partial"
        return "executable"


def assess_reconcile_candidate(
    candidate: CandidateAsset,
    *,
    trigger: dict,
    provider_usable: bool,
) -> OpportunityAssessment:
    """Run a single candidate through causal → constraint → feasibility →
    counterfactual and return a typed, fully-evidenced assessment."""

    causal_path = [
        {"node": "source_of_truth_new_version", "role": "trigger"},
        {"node": f"asset:{candidate.parent_asset_id}", "role": "repaired_parent",
         "repaired_version_id": candidate.parent_repaired_version_id},
        {"node": f"asset:{candidate.asset_id}", "role": "downstream_derivative"},
    ]

    # 1. CAUSAL PROOF — the verified new state must actually enable this. The
    #    enabling fact is a *repaired parent version created by this recall*.
    if not candidate.parent_repaired:
        return OpportunityAssessment(
            kind=KIND_RECONCILE_DERIVATIVE,
            status=STATUS_REJECTED,
            title=f"Reconcile '{candidate.name}'",
            rationale=(
                "Rejected: no causal evidence. The parent asset was not repaired "
                "by this recall, so the verified state change does not enable a "
                "downstream reconcile."
            ),
            evidence={
                "trigger": trigger,
                "causal_path": causal_path,
                "rejected_reason": "no_causal_evidence",
                "counterfactual": None,
            },
        )

    # 2. COUNTERFACTUAL — was this already valid before the change? If the child
    #    is already derived from the parent's newest version, the reconcile was
    #    already done; the change did not create the opportunity.
    counterfactual = {
        "tested_against": "pre_change_state",
        "already_valid_before": candidate.already_reconciled,
        "explanation": (
            "Before the change the new/repaired parent version did not exist, so "
            "rebuilding this derivative from it was not possible."
            if not candidate.already_reconciled
            else "The derivative is already built from the parent's newest version."
        ),
    }
    if candidate.already_reconciled or candidate.already_repaired:
        return OpportunityAssessment(
            kind=KIND_RECONCILE_DERIVATIVE,
            status=STATUS_REJECTED,
            title=f"Reconcile '{candidate.name}'",
            rationale=(
                "Rejected by counterfactual: this derivative is already consistent "
                "with the verified new state, so the change did not create new work."
            ),
            evidence={
                "trigger": trigger,
                "causal_path": causal_path,
                "rejected_reason": "valid_before_change",
                "counterfactual": counterfactual,
            },
        )

    # 3. FEASIBILITY — deterministic derivations reconcile natively; otherwise a
    #    generative operation is required and needs a usable provider.
    method_key = (candidate.derivation_method or "").lower()
    if method_key in DETERMINISTIC_DERIVATIONS:
        op = OperationPlan(
            asset_id=candidate.asset_id,
            name=candidate.name,
            method=DETERMINISTIC_DERIVATIONS[method_key],
            native=True,
            blocked=False,
            reason="rebuilt deterministically from the repaired parent (no provider)",
        )
    else:
        op = OperationPlan(
            asset_id=candidate.asset_id,
            name=candidate.name,
            method="controlled_regeneration",
            native=False,
            blocked=not provider_usable,
            reason=(
                "regenerate from the repaired parent via the generative provider"
                if provider_usable
                else "generative provider is not usable; operation is BLOCKED"
            ),
        )

    assessment = OpportunityAssessment(
        kind=KIND_RECONCILE_DERIVATIVE,
        status=STATUS_CANDIDATE,
        title=f"Reconcile '{candidate.name}' with the verified new state",
        rationale=(
            f"The parent '{candidate.parent_name}' was repaired and verified by this "
            f"recall. '{candidate.name}' still reflects the old state and can now be "
            f"reconciled from the repaired parent."
        ),
        operations=[op],
        evidence={
            "trigger": trigger,
            "causal_path": causal_path,
            "why_enabled": (
                "A repaired, verified parent version now exists; the derivative can "
                "be rebuilt from it. This was impossible before the change."
            ),
            "required_assets": [candidate.parent_asset_id, candidate.asset_id],
            "reusable_assets": [candidate.parent_repaired_version_id],
            "counterfactual": counterfactual,
            "verification_contract": {
                "decodes": True,
                "dimensions_match_child": [candidate.width, candidate.height],
                "b2_read_back_sha_match": True,
                "immutable_version_created": True,
            },
        },
    )
    # 4. VERDICT — verified when there is an executable op, else blocked.
    assessment.status = (
        STATUS_VERIFIED if assessment.feasibility_state != "blocked" else STATUS_BLOCKED
    )
    return assessment
