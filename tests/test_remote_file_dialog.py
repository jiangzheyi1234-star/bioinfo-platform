"""远程文件浏览器对话框测试。"""

import stat
import sys
from unittest.mock import MagicMock

import pytest

from PyQt6.QtWidgets import QApplication


class FakeSFTPAttr:
    def __init__(self, filename, st_mode, st_size=0):
        self.filename = filename
        self.st_mode = st_mode
        self.st_size = st_size


def _make_ssh(entries=None):
    """创建 mock SSH service，sftp().listdir_attr 返回指定条目。"""
    sftp_mock = MagicMock()
    sftp_mock.normalize.return_value = "/home/user"
    sftp_mock.listdir_attr.return_value = entries or []
    sftp_mock.close = MagicMock()

    ssh = MagicMock()
    ssh.sftp.return_value = sftp_mock
    ssh.is_connected = True
    return ssh


@pytest.fixture(scope="session")
def qapp():
    """确保有 QApplication 实例。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_remote_file_dialog_init(qapp):
    """测试对话框初始化和默认主目录。"""
    ssh = _make_ssh()
    from ui.widgets.remote_file_dialog import RemoteFileDialog

    dialog = RemoteFileDialog(ssh, initial_path="/tmp")
    assert dialog._current_path == "/tmp"
    assert dialog.selected_path() == ""


def test_remote_file_dialog_navigate(qapp):
    """测试目录导航。"""
    dir_mode = stat.S_IFDIR | 0o755
    file_mode = stat.S_IFREG | 0o644

    entries = [
        FakeSFTPAttr("subdir", dir_mode),
        FakeSFTPAttr("file.txt", file_mode, st_size=1024),
        FakeSFTPAttr(".hidden", file_mode, st_size=100),
    ]
    ssh = _make_ssh(entries)
    from ui.widgets.remote_file_dialog import RemoteFileDialog

    dialog = RemoteFileDialog(ssh, initial_path="/test")

    # 应该有 2 个可见条目（隐藏文件被过滤）
    assert dialog._tree.topLevelItemCount() == 2
    # 第一个是目录
    assert dialog._tree.topLevelItem(0).text(0) == "subdir"
    assert dialog._tree.topLevelItem(0).text(2) == "目录"
    # 第二个是文件
    assert dialog._tree.topLevelItem(1).text(0) == "file.txt"
    assert dialog._tree.topLevelItem(1).text(2) == "文件"


def test_remote_file_dialog_go_up(qapp):
    """测试上级目录导航。"""
    ssh = _make_ssh()
    from ui.widgets.remote_file_dialog import RemoteFileDialog

    dialog = RemoteFileDialog(ssh, initial_path="/home/user/data")
    dialog._go_up()
    assert dialog._current_path == "/home/user"
    dialog._go_up()
    assert dialog._current_path == "/home"
    dialog._go_up()
    assert dialog._current_path == "/"


def test_format_size():
    """测试文件大小格式化。"""
    from ui.widgets.remote_file_dialog import RemoteFileDialog

    assert RemoteFileDialog._format_size(500) == "500 B"
    assert RemoteFileDialog._format_size(1536) == "1.5 KB"
    assert RemoteFileDialog._format_size(2 * 1024 * 1024) == "2.0 MB"
    assert RemoteFileDialog._format_size(3 * 1024 * 1024 * 1024) == "3.0 GB"
