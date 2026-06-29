"""orchestrator_wrapper.py

Safe wrapper around orchestrator.run_decision that:
- Optionally adapts the prompt via adaptive_prompt_engine
- Calls the original orchestrator.run_decision internally
- Sends the manifest to evolution_engine and enhanced_feedback_engine for learning/suggestion
- Never modifies orchestrator.py; all behavior is additive and guarded
"""

from typing import Tuple, Any, Dict
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("orchestrator_wrapper")

# Lazy imports to avoid import-time failures
try:
    import orchestrator as _orchestrator  # original orchestrator module
    _has_orchestrator = True
except Exception as e:
    _orchestrator = None
    _has_orchestrator = False
    logger.debug("orchestrator import failed: %s", e)

# Optional adaptive prompt engine
try:
    from adaptive_prompt_engine import adapt_prompt
    _has_adaptive = True
except Exception:
    _has_adaptive = False

# Optional enhanced feedback engine
try:
    from enhanced_feedback_engine import get_global_enhanced_feedback_engine
    _has_enhanced = True
except Exception:
    _has_enhanced = False

# Optional evolution engine
try:
    from evolution_engine import get_global_evolution_engine
    _has_evolution = True
except Exception:
    _has_evolution = False

def run_decision(base_prompt: str, model: str = "gmi/seedream-5.0-lite") -> Tuple[str, str, Dict[str, Any], float]:
    """
    Wrapper signature matches the original orchestrator.run_decision.
    Behavior:
      - attempt to adapt the prompt (non-destructive)
      - call the original orchestrator.run_decision (or raise a clear error if missing)
      - post-process manifest with evolution/learning layers (best-effort)
    """
    adapted_prompt = base_prompt
    adapt_meta = {}
    try:
        if _has_adaptive:
            try:
                adapted_prompt, adapt_meta = adapt_prompt(base_prompt, model=model)
            except Exception as e:
                logger.debug("adapt_prompt failed: %s", e)
                adapted_prompt = base_prompt
    except Exception:
        adapted_prompt = base_prompt

    # Call the original orchestrator
    if not _has_orchestrator or not hasattr(_orchestrator, "run_decision"):
        raise RuntimeError("Original orchestrator.run_decision is not available in the environment.")

    try:
        # pass adapted prompt through to the original pipeline
        decision_id, image_url, manifest, score = _orchestrator.run_decision(adapted_prompt, model)
    except Exception as e:
        logger.warning("Wrapped orchestrator.run_decision raised an error: %s", e)
        # Re-raise to keep behavior visible to callers (but can be caught by higher-level UI)
        raise

    # Post-run: best-effort non-blocking processes
    try:
        if _has_evolution:
            try:
                evo = get_global_evolution_engine()
                suggestions = evo.suggest_improvements(manifest)
                # attach suggestions into manifest for visibility (non-invasive)
                manifest.setdefault("_evolution_suggestions", suggestions)
            except Exception as e:
                logger.debug("evolution suggestion failed: %s", e)
    except Exception:
        pass

    try:
        if _has_enhanced:
            try:
                engine = get_global_enhanced_feedback_engine()
                # let enhanced engine observe the final manifest (non-destructive)
                engine.evaluate_decision(manifest)
            except Exception as e:
                logger.debug("enhanced feedback observation failed: %s", e)
    except Exception:
        pass

    # Also include adapt_meta in manifest for visibility (doesn't alter core behavior)
    try:
        manifest.setdefault("_adapt_meta", adapt_meta)
    except Exception:
        pass

    return decision_id, image_url, manifest, score

# Expose a convenience factory to get a wrapped function that preserves original behavior
def get_wrapped_run_decision():
    return run_decision
