# """GMI Cloud image provider adapter (directive sections 2.2, 3).

# This is a real HTTP client. When the API key is missing it reports
# ``configured == False`` and raising ``ProviderConfigError`` on use — it never
# returns fabricated images. The exact request/response shape is centralised here
# so it can be aligned with the current GMI Cloud API without touching the rest of
# the application.
# """
# from __future__ import annotations

# import base64

# from rusted_recall.config import Settings, get_settings
# from rusted_recall.logging_setup import get_logger
# from rusted_recall.providers.base import (
#     GenerationRequest,
#     GenerationResult,
#     ProviderConfigError,
#     ProviderError,
#     classify_http_error,
# )

# logger = get_logger(__name__)


# class GMICloudProvider:
#     name = "gmicloud"

#     def __init__(self, settings: Settings | None = None) -> None:
#         self._settings = settings or get_settings()
#         self.model = self._settings.gmicloud_model

#     @property
#     def configured(self) -> bool:
#         return self._settings.gmicloud_configured

#     def _client(self):  # type: ignore[no-untyped-def]
#         import httpx

#         return httpx.Client(
#             base_url=self._settings.gmicloud_base_url,
#             headers={
#                 "Authorization": f"Bearer {self._settings.gmicloud_api_key}",
#                 "Content-Type": "application/json",
#             },
#             timeout=httpx.Timeout(120.0, connect=10.0),
#         )

#     def generate(self, request: GenerationRequest) -> GenerationResult:
#         if not self.configured:
#             raise ProviderConfigError(
#                 "GMI Cloud API key is not configured. The generation operation is "
#                 "disabled. Set GMICLOUD_API_KEY to enable real repairs."
#             )
#         import httpx

#         payload = {
#             "model": self.model,
#             "prompt": request.prompt,
#             "width": request.width,
#             "height": request.height,
#             "n": 1,
#         }
#         if request.reference_images:
#             payload["image"] = [
#                 base64.b64encode(b).decode("ascii") for b in request.reference_images
#             ]
#         payload.update(request.extra)

#         try:
#             with self._client() as client:
#                 resp = client.post("/v1/images/generations", json=payload)
#             if resp.status_code >= 400:
#                 raise ProviderError(
#                     f"GMI Cloud error {resp.status_code}: {resp.text[:300]}",
#                     category=classify_http_error(resp.status_code),
#                 )
#             data = resp.json()
#         except httpx.TimeoutException as exc:
#             raise ProviderError(f"GMI Cloud timeout: {exc}", category="timeout") from exc
#         except httpx.HTTPError as exc:
#             raise ProviderError(
#                 f"GMI Cloud connection error: {exc}", category="provider_unavailable"
#             ) from exc

#         image_bytes = self._extract_image(data)
#         return GenerationResult(
#             image_bytes=image_bytes,
#             content_type="image/png",
#             provider=self.name,
#             model=self.model,
#             raw_metadata={"response_keys": sorted(data.keys()) if isinstance(data, dict) else []},
#         )

#     @staticmethod
#     def _extract_image(data: dict) -> bytes:
#         # Support common response shapes: {"data":[{"b64_json":...}]} or
#         # {"data":[{"url":...}]}. Never fabricate on failure.
#         try:
#             item = data["data"][0]
#         except (KeyError, IndexError, TypeError) as exc:
#             raise ProviderError(
#                 "GMI Cloud response missing image data", category="corrupt_response"
#             ) from exc
#         if item.get("b64_json"):
#             return base64.b64decode(item["b64_json"])
#         if item.get("url"):
#             import httpx

#             r = httpx.get(item["url"], timeout=60.0)
#             if r.status_code >= 400:
#                 raise ProviderError(
#                     f"could not download generated image: {r.status_code}",
#                     category="corrupt_response",
#                 )
#             return r.content
#         raise ProviderError("GMI Cloud response had no b64_json or url", category="corrupt_response")

#     def health_check(self) -> bool:
#         return self.configured








##############Modifying-Code#######################




"""GMI Cloud image provider adapter."""

from __future__ import annotations

import time
from typing import Any

import httpx

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

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._settings.gmicloud_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self._settings.gmicloud_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(180.0, connect=15.0),
            follow_redirects=True,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.configured:
            raise ProviderConfigError(
                "GMI Cloud API key is not configured. "
                "Set GMICLOUD_API_KEY to enable real repairs."
            )

        inner_payload: dict[str, Any] = {
            "prompt": request.prompt,
            "size": "2K",
            "output_format": "png",
            "watermark": False,
            "sequential_image_generation": "disabled",
            "max_images": 1,
        }

        # GMI Seedream expects image URLs, not raw base64 image bytes.
        reference_urls = request.extra.get("reference_image_urls")
        if reference_urls:
            if isinstance(reference_urls, str):
                inner_payload["image"] = reference_urls
            else:
                inner_payload["image"] = (
                    reference_urls[0]
                    if len(reference_urls) == 1
                    else reference_urls
                )

        # Allow supported caller overrides without overwriting transport metadata.
        for key in (
            "size",
            "output_format",
            "watermark",
            "sequential_image_generation",
            "max_images",
        ):
            if key in request.extra:
                inner_payload[key] = request.extra[key]

        payload = {
            "model": self.model,
            "payload": inner_payload,
        }

        try:
            with self._client() as client:
                create_response = client.post(
                    "/api/v1/ie/requestqueue/apikey/requests",
                    json=payload,
                )

                if create_response.status_code >= 400:
                    raise ProviderError(
                        f"GMI Cloud create error {create_response.status_code}: "
                        f"{create_response.text[:500]}",
                        category=classify_http_error(create_response.status_code),
                    )

                create_data = create_response.json()

                request_id = self._extract_request_id(create_data)
                if not request_id:
                    raise ProviderError(
                        f"GMI Cloud response missing request_id: {create_data}",
                        category="corrupt_response",
                    )

                logger.info(
                    "GMI generation queued",
                    extra={
                        "provider_request_id": request_id,
                        "model": self.model,
                    },
                )

                status_data = self._wait_for_completion(client, request_id)

                media_urls = self._extract_media_urls(status_data)
                if not media_urls:
                    raise ProviderError(
                        f"GMI Cloud succeeded but returned no media_urls: {status_data}",
                        category="corrupt_response",
                    )

                image_response = client.get(media_urls[0])

                if image_response.status_code >= 400:
                    raise ProviderError(
                        f"Could not download generated image: "
                        f"{image_response.status_code}",
                        category="corrupt_response",
                    )

                content_type = (
                    image_response.headers.get("content-type") or "image/png"
                ).split(";")[0]

                return GenerationResult(
                    image_bytes=image_response.content,
                    content_type=content_type,
                    provider=self.name,
                    model=self.model,
                    raw_metadata={
                        "request_id": request_id,
                        "status": "success",
                        "media_url_count": len(media_urls),
                    },
                )

        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"GMI Cloud timeout: {exc}",
                category="timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"GMI Cloud connection error: {exc}",
                category="provider_unavailable",
            ) from exc

    def _wait_for_completion(
        self,
        client: httpx.Client,
        request_id: str,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 240.0

        while time.monotonic() < deadline:
            response = client.get(
                f"/api/v1/ie/requestqueue/apikey/requests/{request_id}"
            )

            if response.status_code >= 400:
                raise ProviderError(
                    f"GMI Cloud status error {response.status_code}: "
                    f"{response.text[:500]}",
                    category=classify_http_error(response.status_code),
                )

            data = response.json()

            status = self._extract_status(data)

            if status == "success":
                return data

            if status in {"failed", "error", "cancelled", "canceled"}:
                raise ProviderError(
                    f"GMI Cloud generation failed: {data}",
                    category="provider_unavailable",
                )

            time.sleep(2.0)

        raise ProviderError(
            "GMI Cloud generation timed out while waiting for completion",
            category="timeout",
        )

    @staticmethod
    def _extract_request_id(data: dict[str, Any]) -> str | None:
        request_id = data.get("request_id") or data.get("id")

        nested = data.get("data")
        if not request_id and isinstance(nested, dict):
            request_id = nested.get("request_id") or nested.get("id")

        return str(request_id) if request_id else None

    @staticmethod
    def _extract_status(data: dict[str, Any]) -> str:
        status = data.get("status")

        nested = data.get("data")
        if not status and isinstance(nested, dict):
            status = nested.get("status")

        return str(status or "").lower()

    @staticmethod
    def _extract_media_urls(data: dict[str, Any]) -> list[str]:
        outcome = data.get("outcome")

        nested = data.get("data")
        if not outcome and isinstance(nested, dict):
            outcome = nested.get("outcome")

        if not isinstance(outcome, dict):
            return []

        urls = outcome.get("media_urls")

        if isinstance(urls, str):
            return [urls]

        if isinstance(urls, list):
            return [str(url) for url in urls if url]

        return []

    def health_check(self) -> bool:
        return self.configured
