"""pytest 配置：项目路径与 Windows 临时目录守护。"""

import os
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import _pytest.tmpdir as pytest_tmpdir
import pytest
from _pytest.tmpdir import TempPathFactory

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def _resolve_configured_basetemp(basetemp: str | os.PathLike[str] | None) -> Path | None:
    if basetemp in (None, ""):
        return None
    candidate = Path(basetemp)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve(strict=False)


def _build_windows_isolated_basetemp() -> Path:
    runs_root = project_root / ".pytest_tmp_runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}_{uuid4().hex[:8]}"
    return (runs_root / run_id).resolve(strict=False)


def _install_windows_cleanup_guard() -> None:
    original_cleanup = getattr(pytest_tmpdir, "_h2o_cleanup_dead_symlinks_original", None)
    if original_cleanup is None:
        original_cleanup = pytest_tmpdir.cleanup_dead_symlinks
        pytest_tmpdir._h2o_cleanup_dead_symlinks_original = original_cleanup

    def _guarded_cleanup_dead_symlinks(root: Path) -> None:
        try:
            original_cleanup(root)
        except PermissionError as exc:
            warnings.warn(
                pytest.PytestWarning(f"Windows temp cleanup skipped for {root}: {exc}"),
                stacklevel=2,
            )

    pytest_tmpdir.cleanup_dead_symlinks = _guarded_cleanup_dead_symlinks


def _install_windows_temp_factory_guard() -> None:
    if getattr(TempPathFactory, "_h2o_windows_temp_guard_installed", False):
        return

    def _guarded_getbasetemp(self: TempPathFactory) -> Path:
        if self._basetemp is not None:
            return self._basetemp

        if self._given_basetemp is not None:
            basetemp = self._given_basetemp
            if basetemp.exists():
                pytest_tmpdir.rm_rf(basetemp)
            basetemp.mkdir()
            basetemp = basetemp.resolve()
        else:
            from_env = os.environ.get("PYTEST_DEBUG_TEMPROOT")
            temproot = Path(from_env or tempfile.gettempdir()).resolve()
            user = pytest_tmpdir.get_user() or "unknown"
            rootdir = temproot.joinpath(f"pytest-of-{user}")
            try:
                rootdir.mkdir(exist_ok=True)
            except OSError:
                rootdir = temproot.joinpath("pytest-of-unknown")
                rootdir.mkdir(exist_ok=True)
            keep = self._retention_count
            if self._retention_policy == "none":
                keep = 0
            basetemp = pytest_tmpdir.make_numbered_dir_with_cleanup(
                prefix="pytest-",
                root=rootdir,
                keep=keep,
                lock_timeout=pytest_tmpdir.LOCK_TIMEOUT,
                mode=0o755,
            )

        assert basetemp is not None, basetemp
        self._basetemp = basetemp
        self._trace("new basetemp", basetemp)
        return basetemp

    def _guarded_mktemp(self: TempPathFactory, basename: str, numbered: bool = True) -> Path:
        basename = self._ensure_relative_to_basetemp(basename)
        if not numbered:
            path = self.getbasetemp().joinpath(basename)
            path.mkdir()
            return path

        path = pytest_tmpdir.make_numbered_dir(root=self.getbasetemp(), prefix=basename, mode=0o755)
        self._trace("mktemp", path)
        return path

    TempPathFactory.getbasetemp = _guarded_getbasetemp
    TempPathFactory.mktemp = _guarded_mktemp
    TempPathFactory._h2o_windows_temp_guard_installed = True


def pytest_configure(config: pytest.Config) -> None:
    """Avoid stale Windows ACL issues from a reused static --basetemp directory."""

    if os.name != "nt":
        return

    _install_windows_cleanup_guard()
    _install_windows_temp_factory_guard()

    configured_basetemp = _resolve_configured_basetemp(getattr(config.option, "basetemp", None))
    default_basetemp = (project_root / ".pytest_tmp").resolve(strict=False)
    if configured_basetemp != default_basetemp:
        return

    config.option.basetemp = str(_build_windows_isolated_basetemp())
    config._tmp_path_factory = TempPathFactory.from_config(config, _ispytest=True)


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """返回一个每个测试独立的临时目录，测试结束后由 pytest 自动清理。"""
    return tmp_path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """返回一个临时 SQLite 数据库路径（文件尚未创建），测试结束后自动清理。"""
    return tmp_path / "test.db"
