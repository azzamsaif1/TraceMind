"""Official Genblaze SDK adapter (directive section 3).

Verifies our GenerationRequest -> upstream Step translation and Asset -> result
mapping, plus factory selection, WITHOUT any network call (the upstream provider
and the output download are faked). The SDK itself is the pinned real package.
"""
from __future__ import annotations

import pytest

from rusted_recall.config import Settings
from rusted_recall.providers.base import GenerationRequest
from rusted_recall.providers.factory import build_primary_provider
from rusted_recall.providers.genblaze_official import (
    OfficialGenblazeImageProvider,
    _classify,
    sdk_available,
)
from rusted_recall.providers.gmicloud import GMICloudProvider
from rusted_recall.repair import (
    ERR_INVALID,
    ERR_QUOTA,
    ERR_UNAVAILABLE,
    is_retryable,
)

pytestmark = pytest.mark.skipif(not sdk_available(), reason="genblaze SDK not installed")


def _settings(**over) -> Settings:
    base = dict(
        gmicloud_api_key="test-key-not-a-placeholder-value",
        gmicloud_model="seedream-5.0-pro",
        gmicloud_poll_interval_seconds=0.0,
        gmicloud_poll_timeout_seconds=5.0,
    )
    base.update(over)
    return Settings(**base)


class _FakeUpstream:
    """Stands in for genblaze_gmicloud.GMICloudImageProvider.invoke."""

    def __init__(self, captured: dict):
        self._captured = captured

    def invoke(self, step, config=None):
        from genblaze_core.models.asset import Asset

        self._captured["step"] = step
        self._captured["config"] = config
        step.assets.append(Asset(url="https://signed/out.png", media_type="image/png"))
        step.provider_payload = {"gmicloud": {"request_id": "req-123", "status": "success"}}
        return step


def test_factory_selects_official_when_enabled():
    p = build_primary_provider(_settings(genblaze_enabled=True))
    assert isinstance(p, OfficialGenblazeImageProvider)
    # Disabled -> direct request-queue adapter.
    p2 = build_primary_provider(_settings(genblaze_enabled=False))
    assert isinstance(p2, GMICloudProvider)


def test_official_generate_maps_step_and_provenance(monkeypatch):
    provider = OfficialGenblazeImageProvider(_settings(genblaze_enabled=True))
    captured: dict = {}
    monkeypatch.setattr(provider, "_provider", lambda: _FakeUpstream(captured))
    monkeypatch.setattr(
        OfficialGenblazeImageProvider, "_download", staticmethod(lambda url: b"PNGBYTES")
    )

    req = GenerationRequest(
        prompt="repair the claim",
        width=1024,
        height=1024,
        extra={"reference_urls": ["https://signed/original.png"]},
    )
    result = provider.generate(req)

    step = captured["step"]
    assert step.model == "seedream-5.0-pro"
    assert step.prompt == "repair the claim"
    assert step.step_type.value == "edit"  # reference present -> edit
    assert [a.url for a in step.inputs] == ["https://signed/original.png"]
    assert step.params["output_format"] == "png"

    assert result.image_bytes == b"PNGBYTES"
    assert result.provider == "gmicloud"
    gb = result.raw_metadata["genblaze"]
    assert gb["official"] is True
    assert gb["request_id"] == "req-123"
    assert gb["core_version"] != "unknown"
    assert gb["connector_version"] != "unknown"


def test_classify_trusts_concrete_codes_over_message():
    # A genuine 5xx server_error stays retryable even if its message text
    # contains words like "invalid"/"not found" (regression guard).
    cat = _classify("server_error", "Upstream 503: invalid gateway, service not found")
    assert cat == ERR_UNAVAILABLE
    assert is_retryable(cat)
    # A concrete invalid_input code is permanent.
    assert _classify("invalid_input", "bad prompt") == ERR_INVALID


def test_classify_recovers_category_from_flattened_unknown():
    # 402 is flattened to "unknown" by the connector; recover quota from text.
    assert _classify("unknown", "GMICloud submit failed (402): Insufficient credits") == ERR_QUOTA
    assert _classify("", "request timed out after 180s") != ERR_QUOTA


def test_official_no_reference_is_generate(monkeypatch):
    provider = OfficialGenblazeImageProvider(_settings(genblaze_enabled=True))
    captured: dict = {}
    monkeypatch.setattr(provider, "_provider", lambda: _FakeUpstream(captured))
    monkeypatch.setattr(
        OfficialGenblazeImageProvider, "_download", staticmethod(lambda url: b"X")
    )
    provider.generate(GenerationRequest(prompt="p", width=512, height=512, extra={}))
    assert captured["step"].step_type.value == "generate"
