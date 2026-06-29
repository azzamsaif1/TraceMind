"""multimodal_interface.py

Abstract adapter for future multimodal capabilities (audio / video).
- No core changes required.
- Provides registration hooks to plug provider implementations later.
- Safe fallbacks prevent import-time crashes.
"""

from typing import Protocol, Dict, Any, Optional, Callable
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("multimodal_interface")

# Define a small protocol (PEP 544) for providers if typing is available
try:
    class MultimodalProviderProtocol(Protocol):
        def generate_audio(self, prompt: str, **kwargs) -> Dict[str, Any]: ...
        def generate_video(self, prompt: str, **kwargs) -> Dict[str, Any]: ...
except Exception:
    MultimodalProviderProtocol = object  # fallback for older runtimes

class NoOpMultimodalProvider:
    """A safe no-op provider that returns informative placeholders."""
    def generate_audio(self, prompt: str, **kwargs) -> Dict[str, Any]:
        return {"status": "not_implemented", "message": "Audio generation provider not configured", "prompt": prompt}

    def generate_video(self, prompt: str, **kwargs) -> Dict[str, Any]:
        return {"status": "not_implemented", "message": "Video generation provider not configured", "prompt": prompt}

# Registry for a provider
_provider: Optional[MultimodalProviderProtocol] = None

def register_provider(provider: MultimodalProviderProtocol):
    global _provider
    _provider = provider
    logger.info("Multimodal provider registered: %s", getattr(provider, "__class__", type(provider)))

def get_provider() -> MultimodalProviderProtocol:
    global _provider
    if _provider is None:
        return NoOpMultimodalProvider()
    return _provider

# Convenience functions
def generate_audio(prompt: str, **kwargs) -> Dict[str, Any]:
    try:
        prov = get_provider()
        return prov.generate_audio(prompt, **kwargs)
    except Exception as e:
        logger.debug("generate_audio failed: %s", e)
        return {"status": "error", "message": str(e)}

def generate_video(prompt: str, **kwargs) -> Dict[str, Any]:
    try:
        prov = get_provider()
        return prov.generate_video(prompt, **kwargs)
    except Exception as e:
        logger.debug("generate_video failed: %s", e)
        return {"status": "error", "message": str(e)}
