"""pytest 配置 — 确保项目根目录在 sys.path 中"""

import sys
from pathlib import Path

import pytest

# 将项目根目录添加到 sys.path，使 core/ 等模块可导入
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """返回一个每个测试独立的临时目录，测试结束后由 pytest 自动清理。"""
    return tmp_path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """返回一个临时 SQLite 数据库路径（文件尚未创建），测试结束后自动清理。"""
    return tmp_path / "test.db"
