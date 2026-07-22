from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

import core.remote_runner.bundle as bundle_module
from core.contracts.remote_runner_sqlite_runtime import (
    REMOTE_RUNNER_SQLITE_MINIMUM_VERSION,
)
from core.remote_runner.bundle import RemoteRunnerBundleBuilder


def _fake_runtime_dir(tmp_path: Path) -> Path:
    runtime_dir = tmp_path / "runtime-source"
    runtime_python = runtime_dir / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("source-runtime\n", encoding="utf-8")
    runtime_python.chmod(0o755)
    return runtime_dir


def test_bundle_builder_probes_the_copied_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_dir = _fake_runtime_dir(tmp_path)
    source_runtime_python = runtime_dir / "bin" / "python"
    original_copytree = bundle_module.shutil.copytree
    observed: list[Path] = []

    def copytree_with_runtime_drift(src, dst, *args, **kwargs):
        result = original_copytree(src, dst, *args, **kwargs)
        if Path(src) == runtime_dir:
            (Path(dst) / "bin" / "python").write_text(
                "copied-runtime-drift\n",
                encoding="utf-8",
            )
        return result

    def require_copied_runtime(runtime_python: Path) -> dict[str, object]:
        observed.append(runtime_python)
        assert runtime_python != source_runtime_python
        assert runtime_python.read_text(encoding="utf-8") == "copied-runtime-drift\n"
        return {
            "minimumVersion": "3.51.3",
            "loadedVersion": "3.53.0",
            "sqlVersion": "3.53.0",
            "ok": True,
        }

    monkeypatch.setattr(bundle_module.shutil, "copytree", copytree_with_runtime_drift)
    monkeypatch.setattr(
        bundle_module,
        "_require_bundled_sqlite_runtime",
        require_copied_runtime,
    )

    bundle = RemoteRunnerBundleBuilder().build(
        version="sqlite-copy-binding-test",
        platform="linux-64",
        runtime_dir=runtime_dir,
    )

    assert observed == [bundle.bundle_dir / "runtime" / "bin" / "python"]
    assert source_runtime_python.read_text(encoding="utf-8") == "source-runtime\n"


def test_bundled_sqlite_probe_executes_a_real_python_subprocess() -> None:
    loaded_version = tuple(sqlite3.sqlite_version_info)

    if loaded_version < REMOTE_RUNNER_SQLITE_MINIMUM_VERSION:
        with pytest.raises(
            RuntimeError,
            match="^REMOTE_RUNNER_BUNDLED_SQLITE_RUNTIME_UNSAFE$",
        ):
            bundle_module._require_bundled_sqlite_runtime(Path(sys.executable))
        return

    evidence = bundle_module._require_bundled_sqlite_runtime(Path(sys.executable))

    loaded_text = ".".join(str(component) for component in loaded_version)
    assert evidence == {
        "minimumVersion": "3.51.3",
        "loadedVersion": loaded_text,
        "sqlVersion": loaded_text,
        "ok": True,
    }


def test_bundled_sqlite_probe_rejects_below_minimum_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "minimumVersion": "3.51.3",
                    "loadedVersion": "3.51.2",
                    "sqlVersion": "3.51.2",
                    "ok": False,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(bundle_module.subprocess, "run", run)

    with pytest.raises(
        RuntimeError,
        match="^REMOTE_RUNNER_BUNDLED_SQLITE_RUNTIME_UNSAFE$",
    ):
        bundle_module._require_bundled_sqlite_runtime(Path("runtime/bin/python"))

    command = observed.pop("command")
    assert isinstance(command, list)
    assert command[:4] == [str(Path("runtime/bin/python")), "-I", "-B", "-c"]
    assert observed == {
        "check": True,
        "capture_output": True,
        "text": True,
        "timeout": 30,
    }
