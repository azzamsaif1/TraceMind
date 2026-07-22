"""Real cryptographic and perceptual hashing (preserved from the original prototype
and strengthened with Hamming-distance / derivative helpers).

Directive sections 5 (preserve SHA-256 + perceptual hashing) and 11 (perceptual-hash
similarity for derivatives).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import imagehash
from PIL import Image

# 64-bit pHash => distances in [0, 64].
PHASH_BITS = 64


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """Streaming SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def perceptual_hash_file(path: str | Path) -> str:
    """Perceptual hash (pHash) of an image, as a hex string."""
    with Image.open(path) as img:
        return str(imagehash.phash(img))


def perceptual_hash_bytes(data: bytes) -> str:
    import io

    with Image.open(io.BytesIO(data)) as img:
        return str(imagehash.phash(img))


def phash_distance(a: str, b: str) -> int:
    """Hamming distance between two pHash hex strings, in [0, 64]."""
    ha = imagehash.hex_to_hash(a)
    hb = imagehash.hex_to_hash(b)
    return ha - hb


def phash_similarity(a: str, b: str) -> float:
    """Normalised similarity in [0, 1] derived from the pHash Hamming distance."""
    return 1.0 - (phash_distance(a, b) / PHASH_BITS)


def is_derivative(a: str, b: str, max_distance: int = 10) -> bool:
    """Heuristic: two images belong to the same derivative family when their pHash
    Hamming distance is small but they are not byte-identical."""
    return 0 < phash_distance(a, b) <= max_distance
