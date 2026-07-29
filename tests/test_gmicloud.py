"""Tests for the GMI Cloud request-queue adapter (Seedream 5.0 Pro).

All provider HTTP is mocked with httpx.MockTransport — no real network calls.
"""
from __future__ import annotations

import httpx
import pytest

from rusted_recall.config import Settings
from rusted_recall.providers.base import GenerationRequest, ProviderError
from rusted_recall.providers.gmicloud import GMICloudProvider


def _settings(**over) -> Settings:
    base = dict(
        gmicloud_api_key="test-key-not-a-placeholder-value",
        gmicloud_base_url="https://console.gmicloud.ai",
        gmicloud_model="seedream-5.0-pro",
        gmicloud_poll_interval_seconds=0.0,
        gmicloud_poll_timeout_seconds=5.0,
    )
    base.update(over)
    return Settings(**base)


def _provider_with(monkeypatch, handler, *, download=b"PNGDATA") -> GMICloudProvider:
    p = GMICloudProvider(_settings())

    def _client():
        return httpx.Client(
            base_url="https://console.gmicloud.ai",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(p, "_client", _client)
    monkeypatch.setattr(GMICloudProvider, "_download", staticmethod(lambda url: download))
    return p


def _req() -> GenerationRequest:
    return GenerationRequest(
        prompt="repair the claim", width=1024, height=1024,
        reference_images=[], operation="edit",
        extra={"reference_urls": ["https://signed/original.png"]},
    )


def test_submit_request_shape(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"request_id": "req-1"})
        return httpx.Response(200, json={"status": "success", "outcome": {"media_urls": ["https://cdn/out.png"]}})

    p = _provider_with(monkeypatch, handler)
    result = p.generate(_req())
    assert result.image_bytes == b"PNGDATA"
    assert result.raw_metadata["request_id"] == "req-1"
    body = captured["body"]
    assert body["model"] == "seedream-5.0-pro"
    assert body["payload"]["prompt"] == "repair the claim"
    assert body["payload"]["image"] == "https://signed/original.png"
    assert body["payload"]["output_format"] == "png"


def test_polls_through_processing_to_success(monkeypatch):
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-2"})
        state["gets"] += 1
        if state["gets"] < 2:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(200, json={"status": "success", "outcome": {"media_urls": [{"url": "https://cdn/out.png"}]}})

    p = _provider_with(monkeypatch, handler)
    result = p.generate(_req())
    assert result.image_bytes == b"PNGDATA"
    assert state["gets"] >= 2


def test_failed_status_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-3"})
        return httpx.Response(200, json={"status": "failed", "error": "content policy"})

    p = _provider_with(monkeypatch, handler)
    with pytest.raises(ProviderError) as exc:
        p.generate(_req())
    assert "failed" in str(exc.value)


def test_timeout_when_never_terminal(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-4"})
        return httpx.Response(200, json={"status": "processing"})

    p = GMICloudProvider(_settings(gmicloud_poll_timeout_seconds=0.01, gmicloud_poll_interval_seconds=0.0))
    monkeypatch.setattr(p, "_client", lambda: httpx.Client(base_url="https://console.gmicloud.ai", transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as exc:
        p.generate(_req())
    assert exc.value.category == "timeout"


@pytest.mark.parametrize("code,category", [(401, "authentication"), (403, "authentication"), (404, "invalid_request"), (402, "quota"), (429, "rate_limit"), (500, "provider_unavailable")])
def test_http_error_classification(monkeypatch, code, category):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": "boom"})

    p = _provider_with(monkeypatch, handler)
    with pytest.raises(ProviderError) as exc:
        p.generate(_req())
    assert exc.value.category == category


def test_success_without_media_urls_is_corrupt(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-5"})
        return httpx.Response(200, json={"status": "success", "outcome": {"media_urls": []}})

    p = _provider_with(monkeypatch, handler)
    with pytest.raises(ProviderError) as exc:
        p.generate(_req())
    assert exc.value.category == "corrupt_response"


def test_unconfigured_provider_disabled():
    p = GMICloudProvider(Settings(gmicloud_api_key=None))
    assert p.configured is False
    with pytest.raises(ProviderError):
        p.generate(_req())
