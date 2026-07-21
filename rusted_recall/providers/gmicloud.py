"""GMI Cloud image provider adapter (directive sections 2.2, 3).

This is a real HTTP client. When the API key is missing it reports
``configured == False`` and raising ``ProviderConfigError`` on use — it never
returns fabricated images. The exact request/response shape is centralised here
so it can be aligned with the current GMI Cloud API without touching the rest of
the application.
"""
from __future__ import annotations

import base64

from rusted_recall.config import Settings, get_settings
from rusted_recall.logging_setup import get_logger
from rusted_recall.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderConfigError,
    ProviderError,
    classify_http_error,
)

logger = get_logger(__name__)


class GMICloudProvider:
    name = "gmicloud"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.gmicloud_model

    @property
    def configured(self) -> bool:
        return self._settings.gmicloud_configured

    def _client(self):  # type: ignore[no-untyped-def]
        import httpx

        return httpx.Client(
            base_url=self._settings.gmicloud_base_url,
            headers={
                "Authorization": f"Bearer {self._settings.gmicloud_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.configured:
            raise ProviderConfigError(
                "GMI Cloud API key is not configured. The generation operation is "
                "disabled. Set GMICLOUD_API_KEY to enable real repairs."
            )
        import httpx

        payload = {
            "model": self.model,
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "n": 1,
        }
        if request.reference_images:
            payload["image"] = [
                base64.b64encode(b).decode("ascii") for b in request.reference_images
            ]
        payload.update(request.extra)

        try:
            with self._client() as client:
                resp = client.post("/v1/images/generations", json=payload)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"GMI Cloud error {resp.status_code}: {resp.text[:300]}",
                    category=classify_http_error(resp.status_code),
                )
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise ProviderError(f"GMI Cloud timeout: {exc}", category="timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"GMI Cloud connection error: {exc}", category="provider_unavailable"
            ) from exc

        image_bytes = self._extract_image(data)
        return GenerationResult(
            image_bytes=image_bytes,
            content_type="image/png",
            provider=self.name,
            model=self.model,
            raw_metadata={"response_keys": sorted(data.keys()) if isinstance(data, dict) else []},
        )

    @staticmethod
    def _extract_image(data: dict) -> bytes:
        # Support common response shapes: {"data":[{"b64_json":...}]} or
        # {"data":[{"url":...}]}. Never fabricate on failure.
        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                "GMI Cloud response missing image data", category="corrupt_response"
            ) from exc
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            import httpx

            r = httpx.get(item["url"], timeout=60.0)
            if r.status_code >= 400:
                raise ProviderError(
                    f"could not download generated image: {r.status_code}",
                    category="corrupt_response",
                )
            return r.content
        raise ProviderError("GMI Cloud response had no b64_json or url", category="corrupt_response")

    def health_check(self) -> bool:
        return self.configured
