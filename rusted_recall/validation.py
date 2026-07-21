"""Automatic validation of repaired assets (directive section 10 "validate")."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from rusted_recall.evidence import ocr_text_match
from rusted_recall.hashing import phash_distance, sha256_bytes


@dataclass
class ValidationResult:
    passed: bool
    requires_human_review: bool
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    output_sha256: str | None = None
    output_dimensions: tuple[int, int] | None = None

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "requires_human_review": self.requires_human_review,
            "checks": self.checks,
            "notes": self.notes,
            "output_sha256": self.output_sha256,
            "output_dimensions": list(self.output_dimensions) if self.output_dimensions else None,
        }


def validate_repaired_image(
    output_bytes: bytes,
    *,
    original_bytes: bytes | None = None,
    original_phash: str | None = None,
    expected_dimensions: tuple[int, int] | None = None,
    expected_mime: str = "image/png",
    new_claim_text: str | None = None,
    deprecated_claim_text: str | None = None,
    extracted_text: str | None = None,
) -> ValidationResult:
    checks: dict[str, bool] = {}
    notes: list[str] = []
    dims: tuple[int, int] | None = None
    sha = sha256_bytes(output_bytes)

    # 1. Decodes successfully.
    try:
        with Image.open(io.BytesIO(output_bytes)) as img:
            img.load()
            dims = img.size
            fmt_mime = Image.MIME.get(img.format or "", "")
        checks["decodes"] = True
    except Exception:  # noqa: BLE001
        checks["decodes"] = False
        return ValidationResult(
            passed=False,
            requires_human_review=False,
            checks=checks,
            notes=["output does not decode as an image"],
            output_sha256=sha,
        )

    # 2. Not an unexpected empty/blank image.
    checks["non_empty"] = len(output_bytes) > 512

    # 3. MIME correct.
    checks["mime_ok"] = (fmt_mime == expected_mime) if expected_mime else True
    if not checks["mime_ok"]:
        notes.append(f"mime {fmt_mime} != expected {expected_mime}")

    # 4. Dimensions match.
    if expected_dimensions is not None:
        checks["dimensions_ok"] = dims == expected_dimensions
        if not checks["dimensions_ok"]:
            notes.append(f"dimensions {dims} != expected {expected_dimensions}")

    # 5. SHA-256 stored (always true here — we computed it).
    checks["sha256_present"] = bool(sha)

    # 6. Output differs from the original.
    if original_bytes is not None:
        checks["differs_from_original"] = sha256_bytes(original_bytes) != sha
        if not checks["differs_from_original"]:
            notes.append("output is byte-identical to the original")

    review = False

    # 7. New claim present (when we can OCR).
    if new_claim_text and extracted_text is not None:
        checks["new_claim_present"] = ocr_text_match(extracted_text, new_claim_text) is not None
        if not checks["new_claim_present"]:
            review = True
            notes.append("new claim not detected in output text; needs review")

    # 8. Deprecated claim absent (when we can OCR).
    if deprecated_claim_text and extracted_text is not None:
        checks["deprecated_claim_absent"] = ocr_text_match(extracted_text, deprecated_claim_text) is None
        if not checks["deprecated_claim_absent"]:
            review = True
            notes.append("deprecated claim still present in output; needs review")

    # 9. Perceptual sanity: output should differ but remain related to the original.
    if original_phash is not None:
        try:
            from rusted_recall.hashing import perceptual_hash_bytes

            out_phash = perceptual_hash_bytes(output_bytes)
            dist = phash_distance(original_phash, out_phash)
            checks["perceptual_changed"] = dist > 0
            if dist == 0:
                review = True
                notes.append("output perceptually identical to original")
        except Exception:  # noqa: BLE001
            notes.append("could not compute output perceptual hash")

    hard_checks = [v for k, v in checks.items()]
    passed = all(hard_checks) and not review
    return ValidationResult(
        passed=passed,
        requires_human_review=review,
        checks=checks,
        notes=notes,
        output_sha256=sha,
        output_dimensions=dims,
    )
