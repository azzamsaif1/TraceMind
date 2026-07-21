"""Provider protocol, request/result types, and error classification."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rusted_recall.repair import (
    ERR_AUTH,
    ERR_INVALID,
    ERR_QUOTA,
    ERR_RATE_LIMIT,
    ERR_SAFETY,
    ERR_TIMEOUT,
    ERR_UNAVAILABLE,
)


class ProviderError(Exception):
    def __init__(self, message: str, category: str = ERR_UNAVAILABLE) -> None:
        super().__init__(message)
        self.category = category


class ProviderConfigError(ProviderError):
    """Raised when a provider is not configured. The operation must be disabled,
    not silently replaced with fake output."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ERR_AUTH)


@dataclass
class GenerationRequest:
    prompt: str
    width: int
    height: int
    reference_images: list[bytes] = field(default_factory=list)
    operation: str = "edit"  # "edit" | "generate"
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    image_bytes: bytes
    content_type: str
    provider: str
    model: str
    raw_metadata: dict = field(default_factory=dict)


@runtime_checkable
class ImageProvider(Protocol):
    name: str
    model: str

    @property
    def configured(self) -> bool: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def health_check(self) -> bool: ...


def classify_http_error(status_code: int) -> str:
    if status_code in (401, 403):
        return ERR_AUTH
    if status_code == 429:
        return ERR_RATE_LIMIT
    if status_code == 402:
        return ERR_QUOTA
    if status_code == 400 or status_code == 422:
        return ERR_INVALID
    if status_code == 451:
        return ERR_SAFETY
    if status_code in (408, 504):
        return ERR_TIMEOUT
    if status_code >= 500:
        return ERR_UNAVAILABLE
    return ERR_UNAVAILABLE
