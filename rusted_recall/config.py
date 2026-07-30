"""Application configuration and the explainable impact-scoring configuration.

Settings are loaded from the environment (and a local ``.env`` in development).
Missing credentials never trigger a silent fallback to fake behaviour: the
relevant capability is reported as unavailable so the UI can show a clear
configuration error (directive sections 2.3 and 16).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "production", "test"] = "development"

    # --- Backblaze B2 (S3-compatible API) ---
    b2_key_id: str | None = None
    b2_app_key: str | None = None
    b2_bucket_name: str | None = None
    b2_s3_endpoint: str | None = None
    b2_region: str = "us-west-004"

    # --- GMI Cloud image provider (Inference Engine request queue) ---
    gmicloud_api_key: str | None = None
    gmicloud_base_url: str = "https://console.gmicloud.ai"
    gmicloud_model: str = "seedream-5.0-pro"
    # Bounded polling for the async request queue.
    gmicloud_poll_interval_seconds: float = 3.0
    gmicloud_poll_timeout_seconds: float = 180.0
    # Presigned reference-image URL lifetime handed to the provider.
    reference_url_expiry_seconds: int = 900

    # --- Genblaze ---
    genblaze_enabled: bool = False

    # --- Repair worker ---
    # When true (default), the web process also drains the durable repair queue
    # on a background thread (dev / single-dyno). Set false when a dedicated
    # ``python -m rusted_recall.worker`` service is deployed (see render.yaml),
    # so the web process only *enqueues* and the separate worker executes.
    run_inline_worker: bool = True

    # --- Database ---
    database_url: str = "postgresql+psycopg://rusted:rusted@localhost:5432/rusted_recall"

    # --- HTTP / CORS ---
    cors_allow_origins: str = "http://localhost:8000"

    # --- Demo cost / quota controls (directive section 25) ---
    demo_max_assets_per_recall: int = 25
    demo_max_repairs_per_recall: int = 3
    demo_max_concurrent_jobs: int = 2

    # --- Storage backend selection ---
    # ``auto`` uses B2 when configured, otherwise local dev storage (only when
    # app_env != production). ``b2`` forces B2. ``local`` forces local dev.
    storage_backend: Literal["auto", "b2", "local"] = "auto"
    local_storage_dir: str = ".local-storage"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def b2_configured(self) -> bool:
        return bool(
            self.b2_key_id
            and self.b2_app_key
            and self.b2_bucket_name
            and self.b2_s3_endpoint
            and not self._is_placeholder(self.b2_key_id)
            and not self._is_placeholder(self.b2_app_key)
            and not self._is_placeholder(self.b2_bucket_name)
        )

    @property
    def gmicloud_configured(self) -> bool:
        return bool(
            self.gmicloud_api_key and not self._is_placeholder(self.gmicloud_api_key)
        )

    @staticmethod
    def _is_placeholder(value: str | None) -> bool:
        if not value:
            return True
        v = value.strip().lower()
        return v.startswith("your-") or v.endswith("-here") or v in {"changeme", ""}


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Impact scoring configuration (directive section 12).
# Weights and thresholds live in configuration and are exposed in the docs and
# the diagnostics panel. They are intentionally data, not magic numbers buried
# in the scoring code.
# ---------------------------------------------------------------------------

# Evidence-component weights. Must sum to 1.0.
EVIDENCE_WEIGHTS: dict[str, float] = {
    "structural_dependency": 0.30,
    "visual_evidence": 0.20,
    "text_evidence": 0.15,
    "semantic_evidence": 0.15,
    "derivation_evidence": 0.10,
    "human_confirmation": 0.10,
}

# Classification thresholds on the final impact score.
IMPACT_THRESHOLDS: dict[str, float] = {
    "directly_affected": 0.80,
    "probably_affected": 0.55,
    "needs_review": 0.25,
}

# Graph traversal limits (directive section 12 "graph traversal").
GRAPH_MAX_DEPTH = 6
# Confidence multiplier applied per additional hop away from the changed source.
GRAPH_EDGE_DECAY = 0.85


def validate_scoring_config() -> None:
    """Fail fast if the scoring configuration is internally inconsistent."""
    total = round(sum(EVIDENCE_WEIGHTS.values()), 6)
    if total != 1.0:
        raise ValueError(f"EVIDENCE_WEIGHTS must sum to 1.0, got {total}")
    t = IMPACT_THRESHOLDS
    if not (0 < t["needs_review"] < t["probably_affected"] < t["directly_affected"] < 1.0):
        raise ValueError("IMPACT_THRESHOLDS must be strictly increasing within (0, 1)")
