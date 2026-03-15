"""Application entrypoint."""

import logging
import os
import sys

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")

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


def _configure_logging() -> None:
    logs_dir = os.path.join(root_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        os.path.join(logs_dir, "app.log"),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)


def main():
    try:
        _configure_logging()
        logging.info("Starting H2OMeta UI")
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
        import traceback

        logs_dir = os.path.join(root_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        startup_handler = logging.FileHandler(
            os.path.join(logs_dir, "startup_error.log"),
            encoding="utf-8",
        )
        startup_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(startup_handler)
        logging.error("Startup failed:\n%s", traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
