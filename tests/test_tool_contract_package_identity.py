from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="tool-package-identity-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def test_added_dependency_contract_records_package_identity_from_package_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
        },
    )

    assert saved["version"] == "9.5"
    assert saved["toolContract"]["package"] == {
        "name": "coreutils",
        "packageSpec": "conda-forge::coreutils=9.5",
        "source": "conda-forge",
        "version": "9.5",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
    }


def test_added_dependency_rejects_unversioned_package_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "conda-forge::coreutils",
                "name": "coreutils",
                "source": "conda-forge",
                "packageSpec": "conda-forge::coreutils",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PACKAGE_VERSION_REQUIRED"
    else:
        raise AssertionError("AddedDependency should require a version-locked packageSpec.")


def test_added_dependency_rejects_version_that_conflicts_with_package_spec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "conda-forge::coreutils",
                "name": "coreutils",
                "source": "conda-forge",
                "version": "9.4",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PACKAGE_VERSION_MISMATCH"
    else:
        raise AssertionError("AddedDependency should keep version and packageSpec as one locked identity.")


def test_added_dependency_rejects_source_that_conflicts_with_package_spec_channel(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "bioconda::coreutils",
                "name": "coreutils",
                "source": "bioconda",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PACKAGE_SOURCE_MISMATCH"
    else:
        raise AssertionError("AddedDependency should keep source and packageSpec channel aligned.")


def test_added_dependency_rejects_name_that_conflicts_with_package_spec_name(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    try:
        add_registered_tool(
            cfg,
            {
                "id": "conda-forge::fastqc",
                "name": "fastqc",
                "source": "conda-forge",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PACKAGE_NAME_MISMATCH"
    else:
        raise AssertionError("AddedDependency should keep name and packageSpec package aligned.")
