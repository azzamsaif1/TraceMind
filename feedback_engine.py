import re
import json
from typing import Dict, List, Tuple
from collections import Counter
from memory import list_all_decisions, get_decision

class FeedbackEngine:
    def __init__(self):
        self.patterns = {
            "too_short": {
                "regex": r"^.{1,20}$",
                "hint": "Avoid very brief prompts. Expand with context, lighting, and style."
            },
            "no_lighting": {
                "regex": r"(?i)(lighting|sunlight|shadow|bright|dark)",
                "hint": "Specify lighting conditions (e.g., golden hour, neon)."
            },
            "no_style": {
                "regex": r"(?i)(style|art|photorealistic|anime|cinematic|vintage)",
                "hint": "Define an artistic style (photorealistic, cyberpunk, watercolor)."
            },
            "no_subject": {
                "regex": r"(?i)(person|building|tree|robot|vehicle|city|landscape)",
                "hint": "Clarify the main subject clearly."
            }
        }

        self.failure_profiles = Counter()
        self.wisdom_cache = None

    def evaluate_decision(self, decision_data: Dict) -> Dict:
        """
        Evaluate a decision based on the prompt text (no VLM required for efficiency).
        """
        prompt = decision_data.get("prompt", "")
        score = 0.7  # baseline score
        reasons = []

        # 1. Prompt length analysis (more detail = better image generation)
        if len(prompt) < 15:
            score -= 0.3
            reasons.append("Very short prompt")
        elif len(prompt) > 60:
            score += 0.2
            reasons.append("Rich descriptive detail")

        # 2. Strong quality keywords
        strong_keywords = [
            "cinematic", "detailed", "hdr", "8k",
            "ultra", "intricate", "masterpiece", "sharp"
        ]
        has_strong = any(kw in prompt.lower() for kw in strong_keywords)
        if has_strong:
            score += 0.15
            reasons.append("Quality-enhancing keywords")

        # 3. Structure analysis (commas improve prompt clarity)
        comma_count = prompt.count(',')
        if comma_count > 3:
            score += 0.1
        elif comma_count == 0:
            score -= 0.1
            reasons.append("No structural commas")

        # 4. Capitalization check (minor quality signal)
        if not re.search(r'[A-Z]', prompt):
            score -= 0.05

        # Clamp score between 0 and 1
        score = max(0.0, min(1.0, score))

        # Update failure profile for adaptive learning
        status = "success" if score >= 0.6 else "failure"
        if status == "failure":
            for key, val in self.patterns.items():
                if not re.search(val["regex"], prompt):
                    self.failure_profiles[key] += 1

        return {
            "decision_id": decision_data.get("decision_id"),
            "score": round(score, 3),
            "status": status,
            "reasons": reasons,
            "failures_detected": dict(self.failure_profiles)
        }

    def get_adaptive_wisdom(self) -> str:
        """
        Extract cumulative system wisdom to improve future prompts.
        """
        if self.failure_profiles:
            top_failures = self.failure_profiles.most_common(2)
            hints = []

            for key, count in top_failures:
                if count >= 1 and key in self.patterns:
                    hints.append(f"- {self.patterns[key]['hint']}")

            if hints:
                return (
                    " [SYSTEM WISDOM] Based on past generations, adapt the prompt to improve quality:\n"
                    + "\n".join(hints)
                )

        return ""

def get_global_feedback_engine():
    """
    Singleton pattern to preserve memory across sessions.
    """
    if not hasattr(get_global_feedback_engine, "engine"):
        get_global_feedback_engine.engine = FeedbackEngine()
    return get_global_feedback_engine.engine
