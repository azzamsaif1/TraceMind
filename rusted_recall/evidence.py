"""Multimodal dependency-evidence engine (directive sections 11-12).

Every method produces a structured Evidence record (edge type, confidence,
evidence type, details, algorithm version, timestamp). We store the full
evidence, not only a final score. Computations are real and deterministic:

* exact SHA-256 duplicate detection,
* perceptual-hash derivative detection (Hamming distance),
* OCR / visible-text claim match (normalised substring match),
* semantic text similarity (token cosine over normalised terms),
* visual similarity (perceptual-hash based),
* explicit declaration and parent-child derivation.

Heavier embedding/vision models (CLIP, sentence-transformers) are optional
enhancements reported via ``analysis_capabilities`` and are never required for a
correct, deployable result.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from rusted_recall.hashing import phash_similarity

ALGO_VERSION = "evidence-engine/1.0.0"

# Edge / evidence types (directive section 4 "analyze dependencies").
EDGE_EXPLICIT = "explicit_declaration"
EDGE_MANIFEST = "generation_manifest"
EDGE_PROMPT = "prompt_reference"
EDGE_SHA256_DUPLICATE = "sha256_duplicate"
EDGE_PHASH_DERIVATIVE = "phash_derivative"
EDGE_OCR_TEXT = "ocr_text_match"
EDGE_SEMANTIC = "semantic_similarity"
EDGE_VISUAL = "visual_similarity"
EDGE_PARENT_CHILD = "parent_child_derivation"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Evidence:
    edge_type: str
    confidence: float
    evidence_type: str
    details: dict
    algorithm_version: str = ALGO_VERSION
    timestamp: str = field(default_factory=_now)
    human_confirmed: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def token_cosine(a: str, b: str) -> float:
    """Cosine similarity over term-frequency vectors. Deterministic, no model."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    va: dict[str, int] = {}
    vb: dict[str, int] = {}
    for t in ta:
        va[t] = va.get(t, 0) + 1
    for t in tb:
        vb[t] = vb.get(t, 0) + 1
    common = set(va) & set(vb)
    dot = sum(va[t] * vb[t] for t in common)
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


# --- individual evidence detectors ---------------------------------------

def explicit_declaration(confidence: float = 1.0, note: str = "") -> Evidence:
    return Evidence(
        edge_type=EDGE_EXPLICIT,
        confidence=confidence,
        evidence_type="user_declared",
        details={"note": note},
        human_confirmed=True,
    )


def parent_child(parent_id: str, child_id: str, confidence: float = 1.0) -> Evidence:
    return Evidence(
        edge_type=EDGE_PARENT_CHILD,
        confidence=confidence,
        evidence_type="derivation_tracking",
        details={"parent": parent_id, "child": child_id},
    )


def sha256_duplicate(a_sha: str, b_sha: str) -> Evidence | None:
    if a_sha and a_sha == b_sha:
        return Evidence(
            edge_type=EDGE_SHA256_DUPLICATE,
            confidence=1.0,
            evidence_type="exact_hash",
            details={"sha256": a_sha},
        )
    return None


def phash_derivative(a_phash: str, b_phash: str, max_distance: int = 12) -> Evidence | None:
    sim = phash_similarity(a_phash, b_phash)
    distance = round((1.0 - sim) * 64)
    if 0 < distance <= max_distance:
        return Evidence(
            edge_type=EDGE_PHASH_DERIVATIVE,
            confidence=round(sim, 4),
            evidence_type="perceptual_hash",
            details={"phash_distance": distance, "similarity": round(sim, 4)},
        )
    return None


def visual_similarity(a_phash: str, b_phash: str, threshold: float = 0.7) -> Evidence | None:
    sim = phash_similarity(a_phash, b_phash)
    if sim >= threshold:
        return Evidence(
            edge_type=EDGE_VISUAL,
            confidence=round(sim, 4),
            evidence_type="visual_hash_similarity",
            details={"similarity": round(sim, 4), "method": "phash"},
        )
    return None


def ocr_text_match(extracted_text: str, claim_text: str) -> Evidence | None:
    """Match a visible marketing claim in OCR-extracted asset text."""
    if not extracted_text or not claim_text:
        return None
    norm_text = _normalize(extracted_text)
    norm_claim = _normalize(claim_text)
    if norm_claim and norm_claim in norm_text:
        return Evidence(
            edge_type=EDGE_OCR_TEXT,
            confidence=0.95,
            evidence_type="ocr_exact_claim",
            details={"claim": claim_text, "match": "substring"},
        )
    sim = token_cosine(norm_text, norm_claim)
    if sim >= 0.6:
        return Evidence(
            edge_type=EDGE_OCR_TEXT,
            confidence=round(0.6 + 0.35 * sim, 4),
            evidence_type="ocr_fuzzy_claim",
            details={"claim": claim_text, "token_cosine": round(sim, 4)},
        )
    return None


def semantic_similarity(asset_description: str, source_description: str, threshold: float = 0.4) -> Evidence | None:
    sim = token_cosine(asset_description, source_description)
    if sim >= threshold:
        return Evidence(
            edge_type=EDGE_SEMANTIC,
            confidence=round(sim, 4),
            evidence_type="text_token_cosine",
            details={"token_cosine": round(sim, 4)},
        )
    return None
