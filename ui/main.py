"""Application entrypoint."""

import os
import sys

from PyQt6.QtWidgets import QApplication

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)

if root_dir not in sys.path:
    sys.path.append(root_dir)

from ui.qt_bootstrap import ensure_qt_webengine_ready


def _sanitize_qt_platform() -> None:
    """Avoid forcing offscreen platform for normal interactive runs."""
    platform = (os.environ.get("QT_QPA_PLATFORM") or "").strip().lower()
    if platform == "offscreen":
        os.environ.pop("QT_QPA_PLATFORM", None)


def _import_main_window():
    try:
        # Prefer package import when launched as `python -m ui.main`.
        from .main_window import MainWindow
    except ImportError:
        # Fallback for direct script execution: `python ui/main.py`.
        from main_window import MainWindow
    return MainWindow


def main():
    try:
        ensure_qt_webengine_ready()
        _sanitize_qt_platform()
        MainWindow = _import_main_window()
        app = QApplication(sys.argv)

        font = app.font()
        if os.name == "nt":
            font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Segoe UI Emoji", "Arial"])
        else:
            font.setFamilies(["Arial", "Segoe UI Emoji"])
        app.setFont(font)

        window = MainWindow()
        window.show()

        exit_code = app.exec()
        sys.exit(exit_code)
    except Exception:
        import logging
        import traceback

        logs_dir = os.path.join(root_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        logging.basicConfig(
            filename=os.path.join(logs_dir, "startup_error.log"),
            level=logging.ERROR,
            encoding="utf-8",
        )
        logging.error("Startup failed:\n%s", traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
