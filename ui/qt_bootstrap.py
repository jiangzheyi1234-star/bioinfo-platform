"""Qt bootstrap helpers for consistent WebEngine startup."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def ensure_qt_webengine_ready() -> bool:
    """Prepare QtWebEngine as early as possible.

    Returns ``True`` when QtWebEngine import succeeds, ``False`` otherwise.
    """
    app = QCoreApplication.instance()
    if app is None:
        # Must be set before creating QApplication.
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception as exc:
        logger.warning("QtWebEngine bootstrap failed: %s", exc)
        return False
