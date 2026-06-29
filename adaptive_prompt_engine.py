"""adaptive_prompt_engine.py

Adaptive prompting wrapper:
- Uses hints from an enhanced feedback engine
- Applies style normalization and optimization rules
- Returns an adapted prompt and a small metadata dict

Rules:
- Import-safe and additive-only
- Fast, deterministic, and side-effect free
"""

from typing import Tuple, Dict, Any
import re
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("adaptive_prompt_engine")

# Try to import enhanced feedback engine but degrade gracefully
try:
    from enhanced_feedback_engine import get_global_enhanced_feedback_engine
    _has_enhanced = True
except Exception:
    _has_enhanced = False

# Minor style heuristics
STYLE_RULES = [
    ("photorealistic", ["photorealistic", "photo-realistic", "photo realistic"]),
    ("cinematic", ["cinematic", "cinema", "film"]),
    ("high-detail", ["detailed", "intricate", "ultra-detailed", "masterpiece"])
]

def _normalize_style_tokens(prompt: str) -> str:
    p = prompt.strip()
    # Ensure punctuation & capitalization basics
    if not re.search(r'[A-Z]', p[:10]):
        p = p[:1].upper() + p[1:]
    # Ensure ends without trailing whitespace
    p = p.rstrip()
    return p

def _ensure_style_hint(prompt: str) -> str:
    lower = prompt.lower()
    for canonical, variants in STYLE_RULES:
        if not any(v in lower for v in variants):
            # append one style hint if none of the variants present
            prompt += f", {canonical}"
            break
    return prompt

def adapt_prompt(base_prompt: str, model: str = "gmi/seedream-5.0-lite") -> Tuple[str, Dict[str, Any]]:
    """
    Return (adapted_prompt, metadata).
    Uses enhanced feedback wisdom when available. Must be fast and safe.
    """
    try:
        prompt = _normalize_style_tokens(base_prompt)
        # Add light style optimization
        prompt = _ensure_style_hint(prompt)

        metadata: Dict[str, Any] = {"adapted": False, "rules_applied": []}

        # Apply wisdom-driven adjustments
        if _has_enhanced:
            try:
                engine = get_global_enhanced_feedback_engine()
                wisdom = engine.get_adaptive_wisdom()
                if wisdom:
                    # Keep insertion minimal and safe: add at the end separated by newlines
                    prompt = prompt + "\n\n" + wisdom
                    metadata["adapted"] = True
                    metadata["wisdom_preview"] = wisdom[:240]
                    metadata["rules_applied"].append("wisdom_injection")
            except Exception as e:
                logger.debug("Enhanced engine call failed: %s", e)

        # Small, deterministic tweaking based on model choice
        if "dall-e" in model.lower():
            prompt += " --vibrant colors"
            metadata["rules_applied"].append("model_vibrancy")
        elif "seedream" in model.lower():
            prompt += " --cinematic lighting"
            metadata["rules_applied"].append("model_cinematic")

        return prompt, metadata
    except Exception as e:
        logger.warning("adapt_prompt failed, returning original prompt: %s", e)
        return base_prompt, {"adapted": False, "error": str(e)}
