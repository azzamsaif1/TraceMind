"""Official Genblaze SDK provider adapter (directive section 3).

Executes a real generative repair through the pinned upstream Genblaze runtime
(``genblaze-core`` + ``genblaze-gmicloud``) instead of hand-rolled orchestration.
The upstream ``GMICloudImageProvider`` owns the request-queue submit/poll/fetch
lifecycle; this adapter only translates our :class:`GenerationRequest` into an
upstream ``Step`` and the produced ``Asset`` back into a :class:`GenerationResult`.

If the SDK is not installed the adapter reports ``configured == False`` and the
factory falls back to the direct request-queue provider — it never fabricates
output. Provenance (real genblaze-core / connector versions, provider request id)
is recorded in ``GenerationResult.raw_metadata['genblaze']``.
"""
from __future__ import annotations

import importlib.metadata as im
import importlib.util
from typing import Any

import httpx

from rusted_recall.config import Settings, get_settings
from rusted_recall.logging_setup import get_logger
from rusted_recall.providers.base import (
    GenerationRequest,
    GenerationResult,
    ProviderConfigError,
    ProviderError,
)
from rusted_recall.repair import (
    ERR_AUTH,
    ERR_INVALID,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_SAFETY,
    ERR_TIMEOUT,
    ERR_UNAVAILABLE,
)

logger = get_logger(__name__)

# Upstream ProviderErrorCode.value -> our retry/category taxonomy.
_ERROR_CODE_MAP = {
    "timeout": ERR_TIMEOUT,
    "rate_limit": ERR_RATE_LIMIT,
    "auth_failure": ERR_AUTH,
    "invalid_input": ERR_INVALID,
    "model_error": ERR_INVALID,
    "content_policy": ERR_SAFETY,
    "server_error": ERR_UNAVAILABLE,
    "unknown": ERR_UNAVAILABLE,
}


def _classify(error_code_value: str, message: str) -> str:
    """Map an upstream error to our taxonomy. The connector flattens some HTTP
    statuses (e.g. 402 insufficient credits) to ``unknown`` — recover the real
    category from the message so retry/quota handling stays correct.

    Message reparse is applied ONLY when the upstream code is missing/``unknown``.
    A concrete code (including a genuine ``server_error``, which is retryable)
    is trusted as-is, so a transient 5xx whose message happens to contain words
    like "invalid" or "not found" is not wrongly demoted to a permanent error."""
    if error_code_value and error_code_value != "unknown":
        return _ERROR_CODE_MAP.get(error_code_value, ERR_UNAVAILABLE)
    low = message.lower()
    if "402" in low or "insufficient credit" in low or "quota" in low:
        return ERR_QUOTA
    if "401" in low or "403" in low or "unauthor" in low or "forbidden" in low:
        return ERR_AUTH
    if "429" in low or "rate limit" in low:
        return ERR_RATE_LIMIT
    if "404" in low or "not found" in low or "invalid" in low:
        return ERR_INVALID
    if "timeout" in low or "timed out" in low:
        return ERR_TIMEOUT
    return ERR_UNAVAILABLE


def sdk_available() -> bool:
    """True when the pinned upstream Genblaze packages are importable."""
    return (
        importlib.util.find_spec("genblaze_core") is not None
        and importlib.util.find_spec("genblaze_gmicloud") is not None
    )


def dist_version(name: str) -> str:
    try:
        return im.version(name)
    except im.PackageNotFoundError:  # pragma: no cover - defensive
        return "unknown"


class OfficialGenblazeImageProvider:
    """Adapter over the upstream ``genblaze_gmicloud.GMICloudImageProvider``."""

    name = "gmicloud"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self.model = self._settings.gmicloud_model

    @property
    def configured(self) -> bool:
        return self._settings.gmicloud_configured and sdk_available()

    def _provider(self) -> Any:
        from genblaze_gmicloud import GMICloudImageProvider

        return GMICloudImageProvider(
            api_key=self._settings.gmicloud_api_key,
            poll_interval=self._settings.gmicloud_poll_interval_seconds or 5.0,
            http_timeout=self._settings.gmicloud_poll_timeout_seconds or 120.0,
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self._settings.gmicloud_configured:
            raise ProviderConfigError(
                "GMI Cloud API key is not configured. Set GMICLOUD_API_KEY to enable real repairs."
            )
        if not sdk_available():
            raise ProviderConfigError(
                "Official Genblaze SDK (genblaze-core, genblaze-gmicloud) is not installed."
            )

        from genblaze_core.exceptions import ProviderError as GBProviderError
        from genblaze_core.models.asset import Asset
        from genblaze_core.models.enums import Modality, StepStatus, StepType
        from genblaze_core.models.step import Step

        ref_urls = request.extra.get("reference_urls") or []
        params: dict[str, Any] = {
            "size": request.extra.get("size", "2K"),
            "sequential_image_generation": "disabled",
            "max_images": 1,
            "output_format": "png",
            "watermark": False,
        }
        params.update(request.extra.get("payload_overrides", {}))

        step = Step(
            provider="gmicloud",
            model=self.model,
            step_type=StepType.EDIT if ref_urls else StepType.GENERATE,
            modality=Modality.IMAGE,
            prompt=request.prompt,
            params=params,
            inputs=[Asset(url=u, media_type="image/png") for u in ref_urls],
        )

        try:
            out = self._provider().invoke(
                step, {"timeout": self._settings.gmicloud_poll_timeout_seconds}
            )
        except GBProviderError as exc:
            code = getattr(exc, "error_code", None)
            raise ProviderError(
                f"Genblaze/GMI error: {exc}",
                category=_classify(str(getattr(code, "value", "")), str(exc)),
            ) from exc

        # invoke() returns a failed Step (rather than raising) when the provider
        # rejects the request (e.g. 402 insufficient credits). Surface it honestly.
        if out.status == StepStatus.FAILED or out.error:
            message = out.error or "Genblaze step failed"
            code_value = out.error_code.value if out.error_code else ""
            raise ProviderError(
                f"Genblaze/GMI error: {message}", category=_classify(code_value, message)
            )

        assets = [a for a in out.assets if a.url]
        if not assets:
            raise ProviderError(
                "Genblaze run completed but produced no media URL", category="corrupt_response"
            )
        image_bytes = self._download(assets[0].url)
        request_id = ""
        gmi_payload = out.provider_payload.get("gmicloud") if out.provider_payload else None
        if isinstance(gmi_payload, dict):
            request_id = str(gmi_payload.get("request_id", ""))

        return GenerationResult(
            image_bytes=image_bytes,
            content_type=assets[0].media_type or "image/png",
            provider=self.name,
            model=self.model,
            raw_metadata={
                "genblaze": {
                    "official": True,
                    "core_version": dist_version("genblaze-core"),
                    "connector_version": dist_version("genblaze-gmicloud"),
                    "upstream_provider": "gmicloud-image",
                    "step_id": out.step_id,
                    "request_id": request_id,
                    "media_url_count": len(assets),
                },
            },
        )

    @staticmethod
    def _download(url: str) -> bytes:
        r = httpx.get(url, timeout=60.0)
        if r.status_code >= 400:
            raise ProviderError(
                f"could not download generated image: {r.status_code}",
                category="corrupt_response",
            )
        return r.content

    def health_check(self) -> bool:
        return self.configured
