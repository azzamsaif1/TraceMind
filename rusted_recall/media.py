"""Media helpers: dimensions, preview/thumbnail generation, optional OCR.

OCR uses pytesseract when the binary + package are available; otherwise it is
reported as unavailable and callers fall back to declared text. We never
fabricate OCR output.
"""
from __future__ import annotations

import io

from PIL import Image

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}


def image_dimensions(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def content_type_for(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as img:
        return Image.MIME.get(img.format or "", "application/octet-stream")


def make_preview(data: bytes, max_side: int = 512) -> bytes:
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def ocr_available() -> bool:
    try:
        from shutil import which

        import pytesseract  # noqa: F401

        return which("tesseract") is not None
    except Exception:  # noqa: BLE001
        return False


def extract_text(data: bytes) -> str | None:
    """Return OCR text, or None when OCR is unavailable."""
    if not ocr_available():
        return None
    try:
        import pytesseract

        with Image.open(io.BytesIO(data)) as img:
            return pytesseract.image_to_string(img).strip()
    except Exception:  # noqa: BLE001
        return None
