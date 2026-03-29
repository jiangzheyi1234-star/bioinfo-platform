from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

import pytest

from ui.widgets import report_view


pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _reset_report_profile():
    report_view._PROFILE = None
    yield
    report_view._PROFILE = None


def test_shared_profile_is_app_owned_and_survives_first_parent_teardown(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(report_view, "_profile_storage_root", lambda: tmp_path / "webengine_report")

    parent1 = QWidget()
    profile1 = report_view._get_or_create_profile()

    assert profile1.parent() is qapp
    assert not sip.isdeleted(profile1)

    parent1.deleteLater()
    qapp.processEvents()

    parent2 = QWidget()
    profile2 = report_view._get_or_create_profile()

    assert profile2 is profile1
    assert profile2.parent() is qapp
    assert not sip.isdeleted(profile2)

    parent2.deleteLater()
    qapp.processEvents()


def test_create_report_web_view_reuses_shared_profile_and_sets_expected_settings(
    qapp,
    tmp_path,
    monkeypatch,
):
    created_profiles = []
    created_pages = []

    class _FakeProfile:
        class PersistentCookiesPolicy:
            NoPersistentCookies = object()

        class HttpCacheType:
            MemoryHttpCache = object()

        def __init__(self, name, parent=None):
            self.name = name
            self.parent_obj = parent
            self.cookies_policy = None
            self.cache_type = None
            self.cache_path = None
            self.storage_path = None
            created_profiles.append(self)

        def setPersistentCookiesPolicy(self, policy):
            self.cookies_policy = policy

        def setHttpCacheType(self, cache_type):
            self.cache_type = cache_type

        def setCachePath(self, path):
            self.cache_path = path

        def setPersistentStoragePath(self, path):
            self.storage_path = path

        def parent(self):
            return self.parent_obj

    class _FakePage:
        def __init__(self, profile, parent=None):
            self.profile = profile
            self.parent_obj = parent
            self.background_color = None
            created_pages.append(self)

        def setBackgroundColor(self, color):
            self.background_color = color

    class _FakeSettings:
        def __init__(self):
            self.attributes = {}

        def setAttribute(self, attr, value):
            self.attributes[attr] = value

    class _FakeWebView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._page = None
            self.context_menu_policy = None
            self._settings = _FakeSettings()

        def setPage(self, page):
            self._page = page

        def page(self):
            return self._page

        def setContextMenuPolicy(self, policy):
            self.context_menu_policy = policy

        def settings(self):
            return self._settings

    import PyQt6.QtWebEngineCore as webengine_core
    import PyQt6.QtWebEngineWidgets as webengine_widgets

    monkeypatch.setattr(report_view, "_profile_storage_root", lambda: tmp_path / "webengine_report")
    monkeypatch.setattr(webengine_core, "QWebEngineProfile", _FakeProfile)
    monkeypatch.setattr(webengine_core, "QWebEnginePage", _FakePage)
    monkeypatch.setattr(webengine_widgets, "QWebEngineView", _FakeWebView)

    parent1 = QWidget()
    view1 = report_view.create_report_web_view(
        parent=parent1,
        background="#112233",
        disable_context_menu=True,
        allow_remote_resources=False,
    )
    parent2 = QWidget()
    view2 = report_view.create_report_web_view(
        parent=parent2,
        background="#112233",
        disable_context_menu=True,
        allow_remote_resources=False,
    )

    assert len(created_profiles) == 1
    profile = created_profiles[0]
    assert profile.name == "h2ometa_report_profile"
    assert profile.parent_obj is qapp
    assert profile.cookies_policy is not None
    assert profile.cache_type is not None
    assert profile.cache_path
    assert profile.storage_path

    assert len(created_pages) == 2
    assert created_pages[0].profile is profile
    assert created_pages[0].parent_obj is parent1
    assert created_pages[1].profile is profile
    assert created_pages[1].parent_obj is parent2

    assert view1.page() is created_pages[0]
    assert view2.page() is created_pages[1]
    assert view1.context_menu_policy == Qt.ContextMenuPolicy.NoContextMenu
    assert view2.context_menu_policy == Qt.ContextMenuPolicy.NoContextMenu

    assert view1.settings().attributes
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.JavascriptEnabled] is True
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled] is False
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.WebGLEnabled] is False
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows] is False
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls] is True
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls] is False
    assert view1.settings().attributes[webengine_core.QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled] is False

    parent1.deleteLater()
    parent2.deleteLater()
    qapp.processEvents()


def test_get_or_create_profile_requires_qapplication(monkeypatch):
    report_view._PROFILE = None
    monkeypatch.setattr(report_view.QApplication, "instance", staticmethod(lambda: None))

    with pytest.raises(RuntimeError, match="QApplication must exist before creating shared webengine profile"):
        report_view._get_or_create_profile()
