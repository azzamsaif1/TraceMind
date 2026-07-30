"""Test-only helpers.

``LocalEditProvider`` performs a real, deterministic image transformation (it
draws the new claim onto the original). It is used ONLY inside automated tests /
the CI end-to-end path (directive section 17). It is never imported by the
production application, which requires a real configured provider.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from rusted_recall.providers.base import GenerationRequest, GenerationResult


def visual_png(shapes, size=(256, 256)) -> bytes:
    """Structured image so two versions have a large perceptual-hash distance,
    forcing a genuine visual (generative-required) change rather than a
    deterministic text overlay. Used by tests exercising the generative path."""
    img = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(img)
    for kind, box in shapes:
        if kind == "rect":
            d.rectangle(box, fill=(0, 0, 0))
        elif kind == "ellipse":
            d.ellipse(box, fill=(0, 0, 0))
        elif kind == "line":
            d.line(box, fill=(0, 0, 0), width=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# Two canonical, perceptually-distinct frames for "generative required" scenarios.
VISUAL_OLD = visual_png([("rect", [20, 20, 120, 120])])
VISUAL_NEW = visual_png([("ellipse", [130, 130, 240, 240]), ("line", [0, 0, 256, 256])])


class LocalEditProvider:
    name = "test-local-edit"
    model = "test/local-edit-1"

    @property
    def configured(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if request.reference_images:
            base = Image.open(io.BytesIO(request.reference_images[0])).convert("RGB")
        else:
            base = Image.new("RGB", (request.width, request.height), (240, 240, 240))
        draw = ImageDraw.Draw(base)
        # Deterministic, visible change derived from the repair instruction.
        draw.rectangle([0, base.height - 40, base.width, base.height], fill=(10, 90, 40))
        draw.text((8, base.height - 30), "Daily Botanical Blend", fill=(255, 255, 255))
        buf = io.BytesIO()
        base.save(buf, format="PNG")
        return GenerationResult(
            image_bytes=buf.getvalue(),
            content_type="image/png",
            provider=self.name,
            model=self.model,
            raw_metadata={"deterministic": True},
        )

    def health_check(self) -> bool:
        return True
