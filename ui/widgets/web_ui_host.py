from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from ui.qt_bootstrap import ensure_qt_webengine_ready
from ui.widgets.report_view import create_report_web_view

logger = logging.getLogger(__name__)


def create_local_web_ui_host(
    *,
    parent,
    bridge_name: str,
    bridge_object,
    html_path: Path,
    background: str = "#FFFFFF",
    disable_context_menu: bool = True,
    allow_remote_resources: bool = True,
    raise_on_missing_html: bool = True,
    on_load_finished: Callable[[bool], None] | None = None,
    on_render_process_terminated: Callable[..., None] | None = None,
):
    """Create a local HTML/QWebChannel host with shared defaults."""
    ensure_qt_webengine_ready()

    from PyQt6.QtCore import QUrl
    from PyQt6.QtWebChannel import QWebChannel

    view = create_report_web_view(
        parent=parent,
        background=background,
        disable_context_menu=disable_context_menu,
        allow_remote_resources=allow_remote_resources,
    )
    view.setStyleSheet(f"background: {background}; border: none;")

    if callable(on_load_finished):
        view.loadFinished.connect(on_load_finished)

    render_process_terminated = getattr(view.page(), "renderProcessTerminated", None)
    if render_process_terminated is not None and callable(on_render_process_terminated):
        render_process_terminated.connect(on_render_process_terminated)

    channel = QWebChannel(parent)
    channel.registerObject(str(bridge_name or "").strip(), bridge_object)
    view.page().setWebChannel(channel)

    if html_path.exists():
        view.setUrl(QUrl.fromLocalFile(str(html_path)))
    else:
        message = f"HTML 文件未找到: {html_path}"
        if raise_on_missing_html:
            raise RuntimeError(message)
        logger.error(message)

    return view, channel
