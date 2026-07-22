"""Object storage abstraction. Backblaze B2 (S3-compatible) is the system of record
in production; a local filesystem backend is available only in development."""
from __future__ import annotations

from rusted_recall.config import Settings, get_settings
from rusted_recall.storage.base import (
    StorageBackend,
    StorageConfigError,
    StoredObject,
)


def get_storage(settings: Settings | None = None) -> StorageBackend:
    """Select the storage backend per configuration.

    Production must use B2. In development, if B2 is not configured we fall back
    to a clearly-marked local backend (never presented as B2).
    """
    settings = settings or get_settings()
    choice = settings.storage_backend

    if choice == "b2" or (choice == "auto" and settings.b2_configured):
        if not settings.b2_configured:
            raise StorageConfigError(
                "Backblaze B2 is selected but not configured. Set B2_KEY_ID, "
                "B2_APP_KEY, B2_BUCKET_NAME, and B2_S3_ENDPOINT."
            )
        from rusted_recall.storage.b2 import B2Storage

        return B2Storage(settings)

    if settings.app_env == "production":
        raise StorageConfigError(
            "Production requires Backblaze B2 but it is not configured. Refusing to "
            "use local development storage in production (directive 2.3)."
        )

    from rusted_recall.storage.local import LocalStorage

    return LocalStorage(settings)


__all__ = [
    "StorageBackend",
    "StorageConfigError",
    "StoredObject",
    "get_storage",
]
