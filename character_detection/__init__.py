"""Standalone optional character detection for AutoHDR-style documents.

Heavy ML dependencies are loaded only when the public detector API is used.
"""

from typing import Any

__all__ = ["CharacterDetection", "CharacterDetector", "DetectionResult"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import detector
        return getattr(detector, name)
    raise AttributeError(name)
