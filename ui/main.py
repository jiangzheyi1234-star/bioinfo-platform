"""Application entrypoint."""

import logging
import os
import sys
import time

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --log-level=3")

from PyQt6.QtWidgets import QApplication

from core.utils import get_app_root

_app_root = get_app_root()

if not getattr(sys, "frozen", False):
    _root_str = str(_app_root)
    if _root_str not in sys.path:
        sys.path.append(_root_str)


def _get_logs_dir() -> str:
    """冻结时日志放在 exe 同级目录，开发时放在仓库根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "logs")
    return os.path.join(str(_app_root), "logs")

from ui.qt_bootstrap import ensure_qt_webengine_ready


class _StderrFilter:
    """Filter known noisy native warnings while preserving real errors."""

    def __init__(self, target):
        self._target = target
        self._buffer = ""
        self._blocked_substrings = (
            "libpng warning: iCCP: known incorrect sRGB profile",
        )

    def write(self, data):
        if not data:
            return 0
        self._buffer += str(data)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if not any(token in line for token in self._blocked_substrings):
                self._target.write(line + "\n")
        return len(str(data))

    def flush(self):
        if self._buffer:
            line = self._buffer
            self._buffer = ""
            if not any(token in line for token in self._blocked_substrings):
                self._target.write(line)
        self._target.flush()


def _install_stderr_filter() -> None:
    current = sys.stderr
    if current is None or isinstance(current, _StderrFilter):
        return
    sys.stderr = _StderrFilter(current)


def _sanitize_qt_platform() -> None:
    """Avoid forcing offscreen platform for normal interactive runs."""
    platform = (os.environ.get("QT_QPA_PLATFORM") or "").strip().lower()
    if platform == "offscreen":
        os.environ.pop("QT_QPA_PLATFORM", None)


def _import_main_window():
    try:
        from ui.main_window import MainWindow
    except ImportError:
        # Fallback for direct script execution: `python ui/main.py`.
        from .main_window import MainWindow
    return MainWindow


def _configure_logging() -> None:
    logs_dir = _get_logs_dir()
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

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    if sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)


def main():
    try:
        app_start = time.perf_counter()
        _install_stderr_filter()
        _configure_logging()
        logging.info("Starting H2OMeta UI")
        t0 = time.perf_counter()
        ensure_qt_webengine_ready(eager_import=False)
        logging.info("Startup timing: qt_bootstrap=%.1fms", (time.perf_counter() - t0) * 1000)
        _sanitize_qt_platform()
        t0 = time.perf_counter()
        MainWindow = _import_main_window()
        logging.info("Startup timing: import_main_window=%.1fms", (time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        app = QApplication(sys.argv)
        logging.info("Startup timing: create_qapp=%.1fms", (time.perf_counter() - t0) * 1000)

        font = app.font()
        if os.name == "nt":
            font.setFamilies(["Segoe UI", "Microsoft YaHei UI", "Segoe UI Emoji", "Arial"])
        else:
            font.setFamilies(["Arial", "Segoe UI Emoji"])
        app.setFont(font)

        t0 = time.perf_counter()
        window = MainWindow()
        logging.info("Startup timing: construct_main_window=%.1fms", (time.perf_counter() - t0) * 1000)
        window.show()
        logging.info("Startup timing: to_first_show=%.1fms", (time.perf_counter() - app_start) * 1000)

        exit_code = app.exec()
        sys.exit(exit_code)
    except Exception:
        import traceback

        logs_dir = _get_logs_dir()
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
