"""evolution_engine.py

Lightweight self-evolution suggestion engine:
- Ranks recommendations based on simple heuristics
- Produces safe, non-invasive suggestions (human-reviewable)
- Does not modify any core system files

Typical usage:
- Call suggest_improvements(manifest) after a run to get ranked suggestions
"""

from typing import List, Dict, Any
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("evolution_engine")

class EvolutionEngine:
    def __init__(self):
        # Maintain counters for strategy effectiveness (in-memory)
        self.strategy_scores = {}  # strategy_key -> cumulative_score
        self.history = []  # recent suggestion records

    def suggest_improvements(self, manifest: Dict[str, Any], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Analyze a manifest and return a ranked list of suggestions.
        Each suggestion is a small dict: {"id", "title", "reason", "impact_score"}.
        Non-destructive: consumer must apply suggestions manually.
        """
        try:
            suggestions = []

            score = manifest.get("score", 0.0)
            reasons = manifest.get("evaluation_reasons") or manifest.get("reasons") or []

            # If low score, suggest prompt expansions
            if score < 0.6:
                suggestions.append({
                    "id": "expand_prompt",
                    "title": "Expand prompt with lighting/style/subject",
                    "reason": "Low score; more descriptive prompts improve quality",
                    "impact_score": 0.8
                })

            # If manifest indicates missing wisdom, suggest enabling adaptive wisdom
            if not manifest.get("wisdom_used"):
                suggestions.append({
                    "id": "enable_wisdom",
                    "title": "Use adaptive wisdom layer",
                    "reason": "No adaptive wisdom was applied to this run",
                    "impact_score": 0.5
                })

            # If reasons contain 'No structural commas' or similar, suggest structure
            if any("No structural" in str(r) or "No structural" in str(r).lower() for r in reasons):
                suggestions.append({
                    "id": "improve_structure",
                    "title": "Add commas and phrase separation",
                    "reason": "Prompt structure often correlates with better outputs",
                    "impact_score": 0.4
                })

            # Add lightweight ranking by impact_score then append metadata
            suggestions = sorted(suggestions, key=lambda s: s["impact_score"], reverse=True)[:top_k]

            # Record into history with simple scoring to enable future ranking
            for s in suggestions:
                key = s["id"]
                self.strategy_scores[key] = self.strategy_scores.get(key, 0.0) + s["impact_score"]
                self.history.append({"manifest_id": manifest.get("decision_id"), "suggestion": s})

            return suggestions
        except Exception as e:
            logger.debug("suggest_improvements failed: %s", e)
            return []

# Simple module-level singleton
def get_global_evolution_engine() -> EvolutionEngine:
    if not hasattr(get_global_evolution_engine, "engine"):
        get_global_evolution_engine.engine = EvolutionEngine()
    return get_global_evolution_engine.engine
