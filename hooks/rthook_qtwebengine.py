"""Runtime hook: set QtWebEngine paths for frozen builds."""
import os
import sys

if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    proc = os.path.join(base, "PyQt6", "Qt6", "bin", "QtWebEngineProcess.exe")
    if os.path.exists(proc):
        os.environ["QTWEBENGINEPROCESS_PATH"] = proc

    resources = os.path.join(base, "PyQt6", "Qt6", "resources")
    if os.path.isdir(resources):
        os.environ["QTWEBENGINE_RESOURCES_PATH"] = resources

    locales = os.path.join(
        base, "PyQt6", "Qt6", "translations", "qtwebengine_locales"
    )
    if os.path.isdir(locales):
        os.environ["QTWEBENGINE_LOCALES_PATH"] = locales
