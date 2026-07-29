"""GMI Cloud image provider adapter (directive sections 2.2, 3).

Uses the official GMI Cloud **Inference Engine request queue** (Seedream 5.0
Pro). This is a real async HTTP client: it submits a request, polls with a
bounded timeout, and downloads the produced media. When the API key is missing
it reports ``configured == False`` and raises ``ProviderConfigError`` on use —
it never returns fabricated images.

Flow (per GMI Cloud request-queue contract)::

    POST /api/v1/ie/requestqueue/apikey/requests
        {"model": "seedream-5.0-pro", "payload": {...}}
    -> {"request_id": "..."}
    GET  /api/v1/ie/requestqueue/apikey/requests/{request_id}
    -> {"status": "success", "outcome": {"media_urls": [...]}}
"""
from __future__ import annotations

import time
from typing import Any

from rusted_recall.config import Settings, get_settings
from rusted_recall.logging_setup import get_logger
from rusted_recall.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderConfigError,
    ProviderError,
    classify_http_error,
)
from rusted_recall.repair import ERR_INVALID, ERR_TIMEOUT, ERR_UNAVAILABLE

logger = get_logger(__name__)

_REQUESTS_PATH = "/api/v1/ie/requestqueue/apikey/requests"
_TERMINAL_SUCCESS = {"success", "succeeded", "completed"}
_TERMINAL_FAILURE = {"failed", "error", "cancelled", "canceled"}


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
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.configured:
            raise ProviderConfigError(
                "GMI Cloud API key is not configured. The generation operation is "
                "disabled. Set GMICLOUD_API_KEY to enable real repairs."
            )
        import httpx

        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "size": request.extra.get("size", "2K"),
            "sequential_image_generation": "disabled",
            "max_images": 1,
            "output_format": "png",
            "watermark": False,
        }
        # Seedream expects reference image URLs (presigned, short-lived). Only
        # URLs are sent to the provider — never raw bytes or permanent links.
        ref_urls = request.extra.get("reference_urls") or []
        if ref_urls:
            payload["image"] = ref_urls if len(ref_urls) > 1 else ref_urls[0]
        payload.update(request.extra.get("payload_overrides", {}))

        body = {"model": self.model, "payload": payload}

        try:
            with self._client() as client:
                resp = client.post(_REQUESTS_PATH, json=body)
                if resp.status_code >= 400:
                    raise ProviderError(
                        f"GMI Cloud submit error {resp.status_code}: {resp.text[:300]}",
                        category=classify_http_error(resp.status_code),
                    )
                request_id = self._extract_request_id(resp.json())
                outcome = self._poll(client, request_id)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"GMI Cloud timeout: {exc}", category=ERR_TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"GMI Cloud connection error: {exc}", category=ERR_UNAVAILABLE
            ) from exc

        media_url = self._extract_media_url(outcome)
        image_bytes = self._download(media_url)
        return GenerationResult(
            image_bytes=image_bytes,
            content_type="image/png",
            provider=self.name,
            model=self.model,
            raw_metadata={
                "request_id": request_id,
                "status": outcome.get("status", "success"),
                "media_url_count": len(self._media_urls(outcome)),
            },
        )

    def _poll(self, client, request_id: str) -> dict:  # type: ignore[no-untyped-def]
        deadline = time.monotonic() + self._settings.gmicloud_poll_timeout_seconds
        interval = self._settings.gmicloud_poll_interval_seconds
        while True:
            resp = client.get(f"{_REQUESTS_PATH}/{request_id}")
            if resp.status_code >= 400:
                raise ProviderError(
                    f"GMI Cloud poll error {resp.status_code}: {resp.text[:300]}",
                    category=classify_http_error(resp.status_code),
                )
            data = resp.json()
            status = str(data.get("status", "")).lower()
            if status in _TERMINAL_SUCCESS:
                return data
            if status in _TERMINAL_FAILURE:
                detail = data.get("error") or data.get("message") or status
                raise ProviderError(
                    f"GMI Cloud request {request_id} {status}: {str(detail)[:200]}",
                    category=ERR_UNAVAILABLE if status in ("error",) else ERR_INVALID,
                )
            if time.monotonic() >= deadline:
                raise ProviderError(
                    f"GMI Cloud request {request_id} did not complete within "
                    f"{self._settings.gmicloud_poll_timeout_seconds}s (last status={status})",
                    category=ERR_TIMEOUT,
                )
            time.sleep(interval)

    @staticmethod
    def _extract_request_id(data: dict) -> str:
        for key in ("request_id", "id", "requestId"):
            if isinstance(data, dict) and data.get(key):
                return str(data[key])
        raise ProviderError(
            "GMI Cloud submit response had no request_id", category="corrupt_response"
        )

    @staticmethod
    def _media_urls(outcome: dict) -> list[str]:
        block = outcome.get("outcome") or outcome
        urls = block.get("media_urls") or block.get("mediaUrls") or []
        result: list[str] = []
        for u in urls:
            if isinstance(u, str):
                result.append(u)
            elif isinstance(u, dict) and u.get("url"):
                result.append(str(u["url"]))
        return result

    def _extract_media_url(self, outcome: dict) -> str:
        urls = self._media_urls(outcome)
        if not urls:
            raise ProviderError(
                "GMI Cloud success response had no media_urls",
                category="corrupt_response",
            )
        return urls[0]

    @staticmethod
    def _download(url: str) -> bytes:
        import httpx

        r = httpx.get(url, timeout=60.0)
        if r.status_code >= 400:
            raise ProviderError(
                f"could not download generated image: {r.status_code}",
                category="corrupt_response",
            )
        return r.content

    def health_check(self) -> bool:
        return self.configured
