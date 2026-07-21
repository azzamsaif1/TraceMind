"""Generative-media provider adapters. Real integrations only — a missing
credential disables the operation with a clear error and never fabricates
output (directive sections 2.2, 2.3, 26)."""
from rusted_recall.providers.base import (
    GenerationRequest,
    GenerationResult,
    ImageProvider,
    ProviderConfigError,
    ProviderError,
    classify_http_error,
)

__all__ = [
    "GenerationRequest",
    "GenerationResult",
    "ImageProvider",
    "ProviderConfigError",
    "ProviderError",
    "classify_http_error",
]
