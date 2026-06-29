"""enhanced_feedback_engine.py

Wrapper around the existing FeedbackEngine that adds:
- real-time failure pattern analysis
- automatic insight extraction
- optional lightweight continuous-learning utilities

Design constraints honored:
- Additive only: wraps existing FeedbackEngine (composition)
- Safe imports and try/except to avoid import-time failures
- Exposes a compatible API for evaluate_decision and get_adaptive_wisdom
"""

from typing import Dict, Any, Optional
import threading
import time
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("enhanced_feedback_engine")

# Try to import the project's feedback engine. If it's not present, provide a minimal fallback.
try:
    from feedback_engine import FeedbackEngine, get_global_feedback_engine  # existing module
except Exception:  # pragma: no cover - fallback when missing
    FeedbackEngine = None
    def get_global_feedback_engine():
        class _Stub:
            def __init__(self):
                self.failure_profiles = {}
            def evaluate_decision(self, data):
                return {"decision_id": data.get("decision_id"), "score": 0.5, "status": "failure", "reasons": ["fallback"], "failures_detected": {} }
            def get_adaptive_wisdom(self):
                return ""
        return _Stub()


class EnhancedFeedbackEngine:
    """
    Wraps an existing FeedbackEngine instance to:
      - capture more fine-grained failure patterns
      - surface automated hints
      - maintain a lightweight rolling failure window for "continuous" learning
    """

    def __init__(self, base_engine=None, window_size=100):
        try:
            self.base = base_engine or get_global_feedback_engine()
        except Exception as e:
            logger.warning("Could not get base feedback engine: %s", e)
            self.base = get_global_feedback_engine()

        self.lock = threading.Lock()
        self.window_size = window_size
        self.recent_failures = []  # list of (timestamp, failure_keys)
        self.aggregated_insights = {}  # key -> count

    def _record_failures(self, failure_keys):
        ts = int(time.time())
        with self.lock:
            self.recent_failures.append((ts, tuple(failure_keys)))
            for k in failure_keys:
                self.aggregated_insights[k] = self.aggregated_insights.get(k, 0) + 1
            # Trim window
            if len(self.recent_failures) > self.window_size:
                old_ts, old_keys = self.recent_failures.pop(0)
                for k in old_keys:
                    self.aggregated_insights[k] = max(0, self.aggregated_insights.get(k, 1) - 1)

    def evaluate_decision(self, decision_data: Dict[str, Any]) -> Dict[str, Any]:
        """Call the base evaluator, then enhance diagnostics and failure tracking."""
        try:
            result = self.base.evaluate_decision(decision_data)
        except Exception as e:
            logger.warning("Base evaluate_decision failed: %s", e)
            # Fallback minimal evaluation
            result = {
                "decision_id": decision_data.get("decision_id"),
                "score": 0.0,
                "status": "failure",
                "reasons": ["evaluation_failed"],
                "failures_detected": {}
            }

        # Augment reasons with simple pattern extraction (non-invasive)
        try:
            failures = result.get("failures_detected") or {}
            # Convert to keys list for recording
            failure_keys = [k for k, v in (failures.items() if isinstance(failures, dict) else []) if v]
            if result.get("status") == "failure" and failure_keys:
                self._record_failures(failure_keys)
        except Exception as e:
            logger.debug("Enhanced recording failed: %s", e)

        # Add lightweight meta to result
        try:
            insights = self._top_insights(limit=3)
            if insights:
                result.setdefault("reasons", []).append("Enhanced insights: " + "; ".join(insights))
        except Exception:
            pass

        return result

    def _top_insights(self, limit=3):
        with self.lock:
            items = sorted(self.aggregated_insights.items(), key=lambda kv: kv[1], reverse=True)
            return [f"{k}({v})" for k, v in items[:limit]]

    def get_adaptive_wisdom(self) -> str:
        """
        Merge base engine wisdom and aggregated insights into a single short guidance string.
        Non-invasive: never writes to the base engine state.
        """
        try:
            base_wisdom = ""
            try:
                base_wisdom = self.base.get_adaptive_wisdom() or ""
            except Exception:
                base_wisdom = ""

            top = self._top_insights(limit=4)
            hint_lines = []
            if base_wisdom:
                hint_lines.append(base_wisdom.strip())
            if top:
                hint_lines.append("[ENHANCED SUMMARY] Frequent failures: " + ", ".join(top))

            return "\n".join(hint_lines).strip()
        except Exception as e:
            logger.debug("get_adaptive_wisdom failed: %s", e)
            return ""

# Singleton accessor to keep behavior consistent with existing code patterns
def get_global_enhanced_feedback_engine() -> EnhancedFeedbackEngine:
    if not hasattr(get_global_enhanced_feedback_engine, "engine"):
        try:
            base = get_global_feedback_engine()
        except Exception:
            base = get_global_feedback_engine()
        get_global_enhanced_feedback_engine.engine = EnhancedFeedbackEngine(base_engine=base)
    return get_global_enhanced_feedback_engine.engine
