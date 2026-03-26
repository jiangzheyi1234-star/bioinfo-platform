from __future__ import annotations

from ui.widgets.environment_status_bar import EnvironmentStatusBar


def test_install_status_text_and_click_signal(_ensure_qapp):
    bar = EnvironmentStatusBar()
    clicked = {"count": 0}
    bar.install_status_clicked.connect(lambda: clicked.__setitem__("count", clicked["count"] + 1))

    bar.update_install_status("安装: 2 项失败", "error")
    assert "2 项失败" in bar._install_label.text()
    assert bar._install_icon.pixmap() is not None

    bar._install_label.clicked.emit()
    assert clicked["count"] == 1

    bar.close()
    bar.deleteLater()
    _ensure_qapp.processEvents()
