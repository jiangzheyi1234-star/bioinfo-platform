"""Backward-compatible shim for legacy imports.

Historically callers imported `ui.pages.detection_page.DetectionPage`.
The implementation has moved to `DetectionPageWeb`.
"""

from .detection_page_web import DetectionPageWeb

DetectionPage = DetectionPageWeb

__all__ = ["DetectionPage"]
