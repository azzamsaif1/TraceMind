"""Real integration smoke tests — require live credentials, skipped otherwise.

These are the only tests that touch real external services (directive section
17). Run with real B2 / GMI Cloud env vars set:

    RUN_INTEGRATION=1 GMICLOUD_API_KEY=... pytest tests/test_integration_smoke.py
"""
from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from rusted_recall.config import Settings

RUN = os.getenv("RUN_INTEGRATION") == "1"
pytestmark = pytest.mark.skipif(not RUN, reason="set RUN_INTEGRATION=1 with real credentials")


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (256, 256), (40, 120, 70)).save(buf, format="PNG")
    return buf.getvalue()


def test_gmicloud_generation_real():
    from rusted_recall.providers.base import GenerationRequest
    from rusted_recall.providers.gmicloud import GMICloudProvider

    settings = Settings()
    provider = GMICloudProvider(settings)
    if not provider.configured:
        pytest.skip("GMICLOUD_API_KEY not configured")
    result = provider.generate(
        GenerationRequest(
            prompt="A product photo of a green botanical sparkling water can, studio lighting",
            width=512, height=512, reference_images=[_png()], operation="edit",
        )
    )
    assert result.image_bytes
    Image.open(io.BytesIO(result.image_bytes)).verify()


def test_b2_roundtrip_real():
    from rusted_recall.storage.b2 import B2Storage

    settings = Settings()
    if not settings.b2_configured:
        pytest.skip("B2 not configured")
    storage = B2Storage(settings)
    key = "rusted-recall/_smoke/roundtrip.png"
    data = _png()
    stored = storage.put_bytes(key, data, "image/png", metadata={"sha256": stored_sha(data)})
    assert stored.sha256
    assert storage.get_bytes(key) == data
    assert storage.exists(key)


def stored_sha(data: bytes) -> str:
    from rusted_recall.hashing import sha256_bytes

    return sha256_bytes(data)
