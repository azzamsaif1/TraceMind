"""Provider capability / preflight routing (spec: "attempt generation only when
provider/model is confirmed usable; truthful typed provider states").

Rusted Recall is provider-independent: the planner decides *whether* a repair
needs generation, and only then do we consult the provider. This module answers
"is a usable generative provider available right now, and if not, exactly why?"
in a *typed, truthful* way — without ever making a paid generation call.

Two information sources, combined honestly:

* **Preflight** (no network / no paid call): is a provider configured at all,
  and is a model selected? This yields ``USABLE`` (configured) or
  ``CONFIGURATION_FAILURE`` (nothing set up).
* **Observed runtime state**: the category of the most recent real provider
  attempt (e.g. HTTP 402 → ``INSUFFICIENT_CREDITS``). We never fabricate this —
  it is only ever the classification of a real response.

The typed states map 1:1 to the error taxonomy in :mod:`rusted_recall.repair`
so nothing is invented. A generative operation runs only when the state is
``USABLE``; otherwise it is reported as ``BLOCKED`` with the specific reason.
"""
from __future__ import annotations

from dataclasses import dataclass

from rusted_recall.providers.base import ImageProvider
from rusted_recall.repair import (
    ERR_AUTH,
    ERR_CORRUPT,
    ERR_INVALID,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_SAFETY,
    ERR_TIMEOUT,
    ERR_UNAVAILABLE,
)

# --- typed provider states (spec) ---------------------------------------
USABLE = "usable"
CONFIGURATION_FAILURE = "configuration_failure"
AUTHENTICATION_FAILURE = "authentication_failure"
ACCESS_GATED = "access_gated"
INSUFFICIENT_CREDITS = "insufficient_credits"
UNSUPPORTED_MODEL = "unsupported_model"
RATE_LIMITED = "rate_limited"
SAFETY_BLOCKED = "safety_blocked"
TRANSIENT_FAILURE = "transient_failure"

# Human-readable, non-secret explanations for each state.
STATE_DETAIL: dict[str, str] = {
    USABLE: "Provider is configured and a model is selected; ready to generate.",
    CONFIGURATION_FAILURE: "No generative provider is configured (missing API key/model).",
    AUTHENTICATION_FAILURE: "Provider rejected the credentials (authentication failed).",
    ACCESS_GATED: "The account is not permitted to use this model/endpoint.",
    INSUFFICIENT_CREDITS: "Provider account has insufficient credits (billing condition).",
    UNSUPPORTED_MODEL: "The requested model or endpoint is not available.",
    RATE_LIMITED: "Provider is rate limiting requests; retry later.",
    SAFETY_BLOCKED: "Provider refused the request on safety grounds.",
    TRANSIENT_FAILURE: "Provider is temporarily unavailable; retry later.",
}

# Map the repair error taxonomy → a typed provider state. 402 is the canonical
# "add credits" billing condition and is surfaced distinctly from a bad key.
_CATEGORY_TO_STATE: dict[str, str] = {
    ERR_AUTH: AUTHENTICATION_FAILURE,
    ERR_QUOTA: INSUFFICIENT_CREDITS,
    ERR_INVALID: UNSUPPORTED_MODEL,
    ERR_RATE_LIMIT: RATE_LIMITED,
    ERR_SAFETY: SAFETY_BLOCKED,
    ERR_TIMEOUT: TRANSIENT_FAILURE,
    ERR_UNAVAILABLE: TRANSIENT_FAILURE,
    ERR_CORRUPT: TRANSIENT_FAILURE,
}


def state_for_category(category: str | None) -> str:
    """Typed provider state for an observed error category. Unknown/empty →
    configuration failure (we could not confirm the provider is usable)."""
    if not category:
        return CONFIGURATION_FAILURE
    return _CATEGORY_TO_STATE.get(category, TRANSIENT_FAILURE)


@dataclass(frozen=True)
class ProviderCapability:
    """The typed, truthful answer to "can we generate right now?"."""

    provider: str
    model: str
    state: str
    usable: bool
    detail: str

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "state": self.state,
            "usable": self.usable,
            "detail": self.detail,
        }


def preflight(
    provider: ImageProvider,
    *,
    observed_category: str | None = None,
) -> ProviderCapability:
    """Determine provider capability WITHOUT a paid generation call.

    ``observed_category`` — when supplied — is the classification of the most
    recent *real* provider attempt (e.g. from the last failed job). It refines
    a configured provider's state (e.g. configured but last call returned 402 →
    ``INSUFFICIENT_CREDITS``). It is never synthesised.
    """
    name = getattr(provider, "name", "unknown")
    model = getattr(provider, "model", "")
    if not provider.configured:
        return ProviderCapability(
            provider=name,
            model=model,
            state=CONFIGURATION_FAILURE,
            usable=False,
            detail=STATE_DETAIL[CONFIGURATION_FAILURE],
        )
    if observed_category:
        state = state_for_category(observed_category)
        if state != USABLE:
            return ProviderCapability(
                provider=name,
                model=model,
                state=state,
                usable=False,
                detail=STATE_DETAIL[state],
            )
    return ProviderCapability(
        provider=name,
        model=model,
        state=USABLE,
        usable=True,
        detail=STATE_DETAIL[USABLE],
    )
