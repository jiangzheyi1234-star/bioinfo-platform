"""Qt bootstrap helpers for consistent WebEngine startup."""

from __future__ import annotations

import logging
import os
import platform

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def _configure_windows_webengine_fallback() -> None:
    """Reduce QWebEngine black-screen issues on Windows GPUs."""
    if platform.system().lower() != "windows":
        return

    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_ANGLE_PLATFORM", "warp")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

    chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    required_flags = [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-gpu-rasterization",
        "--disable-zero-copy",
        "--disable-features=VizDisplayCompositor,Vulkan,UseSkiaRenderer",
    ]
    for flag in required_flags:
        if flag not in chromium_flags:
            chromium_flags = f"{chromium_flags} {flag}".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_flags

    if QCoreApplication.instance() is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseOpenGLES, False)


def ensure_qt_webengine_ready() -> bool:
    """Prepare QtWebEngine as early as possible.

    Returns ``True`` when QtWebEngine import succeeds, ``False`` otherwise.
    """
    app = QCoreApplication.instance()
    if app is None:
        # Must be set before creating QApplication.
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
        _configure_windows_webengine_fallback()
    else:
        _configure_windows_webengine_fallback()

    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception as exc:
        logger.warning("QtWebEngine bootstrap failed: %s", exc)
        return False
