"""Stable QWebEngine view wrapper for report/visualization surfaces.

Keep business interaction in Qt native widgets and confine WebEngine usage
to rich display areas (charts/reports/HTML results).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, QStandardPaths
from PyQt6.QtGui import QColor

logger = logging.getLogger(__name__)

_PROFILE = None


def _profile_storage_root() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not base:
        base = str(Path.home() / ".h2ometa")
    root = Path(base) / "webengine_report"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _get_or_create_profile(parent=None):
    global _PROFILE
    if _PROFILE is not None:
        return _PROFILE

    from PyQt6.QtWebEngineCore import QWebEngineProfile

    storage_root = _profile_storage_root()
    profile = QWebEngineProfile("h2ometa_report_profile", parent)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
    profile.setCachePath(str(storage_root / "cache"))
    profile.setPersistentStoragePath(str(storage_root / "storage"))
    _PROFILE = profile
    return _PROFILE


def create_report_web_view(
    *,
    parent=None,
    background: str = "#FFFFFF",
    disable_context_menu: bool = True,
    allow_remote_resources: bool = True,
):
    """Create a hardened QWebEngineView for local report rendering."""
    from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    profile = _get_or_create_profile(parent)
    page = QWebEnginePage(profile, parent)
    view = QWebEngineView(parent)
    view.setPage(page)

    if disable_context_menu:
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

    settings = view.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
    settings.setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
        bool(allow_remote_resources),
    )
    settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)

    try:
        view.page().setBackgroundColor(QColor(background))
    except Exception:
        logger.debug("Failed to set web view background color: %s", background, exc_info=True)

    return view
