"""Native (deterministic) repair transforms — executed locally with NO external
generative provider.

These implement the transformations the Minimal Repair Planner classifies as
deterministic (text overlay for pure-text claim changes, and rebuild-from-parent
for crop/resize derivatives). They produce real, byte-stable artifacts from the
inputs — never simulated success — so a plan with ``generative_operations == 0``
can be fully executed without calling Genblaze, GMI, or any provider.

Hard invariant (spec §1): if the planner selects a deterministic method, the
repair is produced here and the provider is never touched.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

# Planner method -> native transform name.
NATIVE_METHODS = frozenset(
    {"deterministic_crop", "deterministic_resize", "text_overlay"}
)


def is_native_method(method: str) -> bool:
    return method in NATIVE_METHODS


def _load(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


def _encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    # Pillow's default bitmap font is always available and renders
    # deterministically across platforms (no external font files needed).
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10
    except TypeError:  # pragma: no cover - older Pillow
        return ImageFont.load_default()


def apply_text_overlay(
    original_bytes: bytes,
    *,
    new_claim: str,
    old_claim: str | None = None,
) -> bytes:
    """Deterministically stamp the corrected approved claim onto the asset.

    A pure-text Source-of-Truth change (e.g. claim wording) is reconciled by
    compositing the new approved claim as a solid banner at the bottom of the
    image. Same input + same claim always yields the same bytes.
    """
    img = _load(original_bytes)
    w, h = img.size
    band_h = max(28, h // 8)
    draw = ImageDraw.Draw(img)
    # opaque banner so the deprecated on-image wording is visually superseded
    draw.rectangle([(0, h - band_h), (w, h)], fill=(17, 17, 17))
    font = _font(max(12, band_h // 2))
    text = (new_claim or "").strip() or "Updated"
    # left-aligned, vertically centred within the band
    ty = h - band_h + max(2, (band_h - (band_h // 2)) // 2)
    draw.text((10, ty), text, fill=(255, 255, 255), font=font)
    return _encode(img)


def rebuild_from_parent(
    parent_repaired_bytes: bytes,
    *,
    width: int,
    height: int,
    method: str,
) -> bytes:
    """Rebuild a crop/resize derivative from its repaired parent.

    ``deterministic_resize`` scales the repaired parent to the child's
    dimensions. ``deterministic_crop`` scales to cover then centre-crops to the
    child's dimensions. Both are exact, repeatable functions of the parent.
    """
    parent = _load(parent_repaired_bytes)
    tw = max(1, int(width or parent.width))
    th = max(1, int(height or parent.height))
    if method == "deterministic_crop":
        # scale to cover, then centre-crop
        scale = max(tw / parent.width, th / parent.height)
        rw, rh = max(1, round(parent.width * scale)), max(1, round(parent.height * scale))
        resized = parent.resize((rw, rh), Image.Resampling.LANCZOS)
        left = (rw - tw) // 2
        top = (rh - th) // 2
        out = resized.crop((left, top, left + tw, top + th))
    else:  # deterministic_resize (and any other deterministic rebuild)
        out = parent.resize((tw, th), Image.Resampling.LANCZOS)
    return _encode(out)
