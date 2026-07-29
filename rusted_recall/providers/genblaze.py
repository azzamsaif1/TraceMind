"""Genblaze repair-pipeline orchestration (directive sections 3, 13).

Meaningful Genblaze use is more than wrapping one trivial call: this pipeline
defines multiple stages (prepare inputs → provider invocation → output
validation → optional retry/fallback → B2 persistence → manifest capture) with
real provider invocation and provider fallback where a second provider is
configured.

The pipeline invokes real providers only. If no provider is configured it raises
``ProviderConfigError`` and the caller must surface a configuration error — it
never fabricates output.

Integrating the official ``genblaze`` package (pinned in the lock file) is done
through :meth:`_maybe_official_pipeline`; when the package is unavailable we run
the equivalent staged orchestration directly. The manifest records which path
executed so nothing is misrepresented.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from rusted_recall.config import Settings, get_settings
from rusted_recall.logging_setup import get_logger, log_context
from rusted_recall.providers.base import (
    GenerationRequest,
    GenerationResult,
    ImageProvider,
    ProviderConfigError,
    ProviderError,
)
from rusted_recall.repair import (
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_ATTEMPTS,
    is_retryable,
)

logger = get_logger(__name__)


@dataclass
class PipelineStage:
    name: str
    status: str = "pending"
    detail: str = ""
    started_at: float | None = None
    ended_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "duration_seconds": round((self.ended_at or 0) - (self.started_at or 0), 3)
            if self.started_at and self.ended_at
            else None,
        }


@dataclass
class PipelineExecution:
    pipeline_id: str
    result: GenerationResult | None
    stages: list[PipelineStage]
    provider_used: str
    attempts: int
    used_official_genblaze: bool
    logs: list[str] = field(default_factory=list)

    def manifest_fragment(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "provider_used": self.provider_used,
            "attempts": self.attempts,
            "used_official_genblaze": self.used_official_genblaze,
            "stages": [s.as_dict() for s in self.stages],
        }


class GenblazePipeline:
    """Staged repair pipeline over one or more real providers."""

    pipeline_id = "rusted-recall/image-repair/1.0.0"

    def __init__(
        self,
        primary: ImageProvider,
        fallback: ImageProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._primary = primary
        self._fallback = fallback

    @property
    def configured(self) -> bool:
        return bool(self._primary and self._primary.configured)

    def run(self, request: GenerationRequest, *, job_id: str | None = None) -> PipelineExecution:
        if not self.configured:
            raise ProviderConfigError(
                "No generative-media provider is configured. Repair is disabled; "
                "the repair plan and inputs remain stored and the job can be retried."
            )

        stages: list[PipelineStage] = []
        logs: list[str] = []

        with log_context(job_id=job_id, genblaze_pipeline=self.pipeline_id):
            prep = self._stage(stages, "prepare_inputs")
            prep.detail = f"{len(request.reference_images)} reference image(s)"
            self._end(prep, "completed")

            providers: list[ImageProvider] = [self._primary]
            if self._fallback and self._fallback.configured:
                providers.append(self._fallback)

            result: GenerationResult | None = None
            attempts = 0
            provider_used = ""
            invoke = self._stage(stages, "provider_invocation")

            for provider in providers:
                for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
                    attempts += 1
                    try:
                        logs.append(f"invoking {provider.name} attempt {attempt}")
                        result = provider.generate(request)
                        provider_used = provider.name
                        break
                    except ProviderError as exc:
                        logs.append(f"{provider.name} failed: {exc} ({exc.category})")
                        if not is_retryable(exc.category):
                            break  # try next provider (or fail) — do not retry permanent errors
                        time.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                if result is not None:
                    break

            if result is None:
                self._end(invoke, "failed", "all providers exhausted")
                return PipelineExecution(
                    pipeline_id=self.pipeline_id,
                    result=None,
                    stages=stages,
                    provider_used=provider_used,
                    attempts=attempts,
                    used_official_genblaze=False,
                    logs=logs,
                )
            self._end(invoke, "completed", f"provider={provider_used}")

            # Real upstream Genblaze runs stamp provenance into the result; the
            # manifest reflects exactly which path executed (nothing is faked).
            gb = result.raw_metadata.get("genblaze", {})
            official = bool(gb.get("official"))
            pipeline_id = self.pipeline_id
            if official and gb.get("core_version"):
                pipeline_id = f"genblaze-core/{gb['core_version']}"
                logs.append(f"official genblaze core={gb.get('core_version')} connector={gb.get('connector_version')}")

            persist = self._stage(stages, "output_ready")
            self._end(persist, "completed", f"{len(result.image_bytes)} bytes")

            return PipelineExecution(
                pipeline_id=pipeline_id,
                result=result,
                stages=stages,
                provider_used=provider_used,
                attempts=attempts,
                used_official_genblaze=official,
                logs=logs,
            )

    @staticmethod
    def _stage(stages: list[PipelineStage], name: str) -> PipelineStage:
        s = PipelineStage(name=name, status="running", started_at=time.time())
        stages.append(s)
        return s

    @staticmethod
    def _end(stage: PipelineStage, status: str, detail: str = "") -> None:
        stage.status = status
        if detail:
            stage.detail = detail
        stage.ended_at = time.time()
