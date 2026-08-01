"""Provider capability / preflight routing — typed provider states without any
paid generation call (spec: capability/preflight routing, truthful states)."""
from __future__ import annotations

from rusted_recall.providers import preflight as pf
from rusted_recall.repair import (
    ERR_AUTH,
    ERR_INVALID,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_TIMEOUT,
    ERR_UNAVAILABLE,
)


class _Provider:
    name = "gmicloud"
    model = "seedream-5.0-pro"

    def __init__(self, configured: bool) -> None:
        self._configured = configured
        self.generate_calls = 0

    @property
    def configured(self) -> bool:
        return self._configured

    def generate(self, request):  # noqa: ANN001, ANN201 - test double
        self.generate_calls += 1
        raise AssertionError("preflight must never make a paid generation call")

    def health_check(self) -> bool:
        return self._configured


def test_unconfigured_provider_is_configuration_failure():
    p = _Provider(configured=False)
    cap = pf.preflight(p)
    assert cap.state == pf.CONFIGURATION_FAILURE
    assert cap.usable is False
    assert p.generate_calls == 0  # no paid call


def test_configured_provider_is_usable_without_a_call():
    p = _Provider(configured=True)
    cap = pf.preflight(p)
    assert cap.state == pf.USABLE
    assert cap.usable is True
    assert p.generate_calls == 0


def test_402_maps_to_insufficient_credits_not_usable():
    p = _Provider(configured=True)
    cap = pf.preflight(p, observed_category=ERR_QUOTA)
    assert cap.state == pf.INSUFFICIENT_CREDITS
    assert cap.usable is False
    assert "credits" in cap.detail.lower()


def test_observed_category_state_mapping():
    assert pf.state_for_category(ERR_AUTH) == pf.AUTHENTICATION_FAILURE
    assert pf.state_for_category(ERR_QUOTA) == pf.INSUFFICIENT_CREDITS
    assert pf.state_for_category(ERR_INVALID) == pf.UNSUPPORTED_MODEL
    assert pf.state_for_category(ERR_RATE_LIMIT) == pf.RATE_LIMITED
    assert pf.state_for_category(ERR_TIMEOUT) == pf.TRANSIENT_FAILURE
    assert pf.state_for_category(ERR_UNAVAILABLE) == pf.TRANSIENT_FAILURE
    assert pf.state_for_category(None) == pf.CONFIGURATION_FAILURE


def test_capability_dict_is_serialisable_and_non_secret():
    p = _Provider(configured=True)
    d = pf.preflight(p, observed_category=ERR_QUOTA).as_dict()
    assert set(d) == {"provider", "model", "state", "usable", "detail"}
    # No credential material is ever included.
    assert "key" not in str(d).lower() or "api" not in str(d).lower()
