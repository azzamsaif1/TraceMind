"""Build the generation pipeline from settings.

Returns a configured GenblazePipeline when a real provider is available, or
raises ProviderConfigError. The web layer surfaces the error as a disabled
operation — it never substitutes fake output (directive section 2.3).
"""
from __future__ import annotations

from rusted_recall.config import Settings, get_settings
from rusted_recall.providers.base import ImageProvider, ProviderConfigError
from rusted_recall.providers.genblaze import GenblazePipeline
from rusted_recall.providers.gmicloud import GMICloudProvider


def build_primary_provider(settings: Settings | None = None) -> ImageProvider:
    settings = settings or get_settings()
    # GMI Cloud is the referenced real provider. Additional providers can be
    # registered here and selected via ProviderConfiguration.
    return GMICloudProvider(settings)


def provider_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    provider = build_primary_provider(settings)
    return {
        "provider": provider.name,
        "model": provider.model,
        "configured": provider.configured,
        "genblaze_enabled": settings.genblaze_enabled,
    }


def build_pipeline(settings: Settings | None = None) -> GenblazePipeline:
    settings = settings or get_settings()
    primary = build_primary_provider(settings)
    if not primary.configured:
        raise ProviderConfigError(
            "No generative-media provider is configured. Set GMICLOUD_API_KEY to enable repairs."
        )
    return GenblazePipeline(primary=primary, settings=settings)
