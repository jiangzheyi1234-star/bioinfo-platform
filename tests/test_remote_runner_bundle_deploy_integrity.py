from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import core.remote_runner.bootstrap_bundle as bundle_module
from core.remote_runner.bootstrap_bundle import RemoteRunnerBootstrapBundleMixin


class BundleDeployError(RuntimeError):
    pass


class FakeSshService:
    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        upload_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.upload_error = upload_error

    def upload(self, local_path: str, remote_path: str) -> None:
        self.events.append(("upload", local_path, remote_path))
        if self.upload_error is not None:
            raise self.upload_error


class Deployer(RemoteRunnerBootstrapBundleMixin):
    _manager_error = BundleDeployError

    def __init__(self, *, fail_step: str = "") -> None:
        self.events: list[tuple[Any, ...]] = []
        self.fail_step = fail_step

    def _run_checked(
        self,
        _ssh_service,
        command: str,
        *,
        step: str,
        timeout: int,
    ) -> None:
        self.events.append(("run", step, command, timeout))
        if step == self.fail_step:
            raise BundleDeployError(f"{step} failed")

    def _write_remote_text_atomic(
        self,
        _ssh_service,
        *,
        path: str,
        content: str,
        step: str,
        timeout: int,
    ) -> None:
        self.events.append(("write", step, path, content, timeout))

    def _cleanup_remote_bundle(
        self,
        _ssh_service,
        remote_bundle: str,
        *,
        step: str,
    ) -> None:
        self.events.append(("cleanup", step, remote_bundle))


def _paths() -> SimpleNamespace:
    return SimpleNamespace(
        bundle="/opt/h2o/current/runner bundle.tar.gz",
        release="/opt/h2o/releases/v1 with space",
        runtime_state="/opt/h2o/state/runtime.json",
        artifact_sha="/opt/h2o/releases/v1 with space/artifact.sha256",
        remote_directories=lambda: [
            "/opt/h2o/current",
            "/opt/h2o/releases/v1 with space",
        ],
    )


def _artifact(
    tmp_path: Path, payload: bytes = b"verified runner bundle"
) -> SimpleNamespace:
    archive = tmp_path / "remote runner.tar.gz"
    archive.write_bytes(payload)
    return SimpleNamespace(
        archive_path=archive,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_bundle_upload_is_verified_and_atomically_published_before_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bundle_module.secrets, "token_hex", lambda _size: "1" * 32)
    artifact = _artifact(tmp_path)
    paths = _paths()
    deployer = Deployer()
    ssh_service = FakeSshService(deployer.events)

    deployer._deploy_service_runtime_bundle(
        ssh_service=ssh_service,
        artifact=artifact,
        paths=paths,
    )

    remote_upload = f"{paths.bundle}.upload-{'1' * 32}.tmp"
    upload = next(event for event in deployer.events if event[0] == "upload")
    assert upload == ("upload", str(artifact.archive_path), remote_upload)
    assert remote_upload != paths.bundle

    verify_index = next(
        index
        for index, event in enumerate(deployer.events)
        if event[:2] == ("run", "verify and publish remote runner bundle")
    )
    stop_index = next(
        index
        for index, event in enumerate(deployer.events)
        if event[:2] == ("run", "clear previous remote runner service")
    )
    extract_index = next(
        index
        for index, event in enumerate(deployer.events)
        if event[:2] == ("run", "extract remote runner bundle")
    )
    marker_index = next(
        index
        for index, event in enumerate(deployer.events)
        if event[:2] == ("write", "write remote runner artifact marker")
    )
    assert verify_index < stop_index < extract_index < marker_index
    verify_command = deployer.events[verify_index][2]
    assert "sha256sum '/opt/h2o/current/runner bundle.tar.gz.upload-" in verify_command
    assert artifact.sha256 in verify_command
    assert verify_command.index("sha256sum") < verify_command.index("mv -f")
    assert "mv -f '/opt/h2o/current/runner bundle.tar.gz.upload-" in verify_command
    assert "'/opt/h2o/current/runner bundle.tar.gz'" in verify_command

    assert (
        "write",
        "write remote runner artifact marker",
        paths.artifact_sha,
        artifact.sha256,
        10,
    ) in deployer.events
    assert deployer.events[-1] == (
        "cleanup",
        "cleanup remote runner bundle",
        paths.bundle,
    )


def test_local_sha_mismatch_fails_before_any_remote_action(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)
    artifact.sha256 = "0" * 64
    deployer = Deployer()
    ssh_service = FakeSshService(deployer.events)

    with pytest.raises(BundleDeployError, match="local SHA-256 mismatch"):
        deployer._deploy_service_runtime_bundle(
            ssh_service=ssh_service,
            artifact=artifact,
            paths=_paths(),
        )

    assert deployer.events == []


def test_remote_sha_failure_cleans_temp_without_stopping_or_extracting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bundle_module.secrets, "token_hex", lambda _size: "2" * 32)
    artifact = _artifact(tmp_path)
    paths = _paths()
    deployer = Deployer(fail_step="verify and publish remote runner bundle")
    ssh_service = FakeSshService(deployer.events)

    with pytest.raises(BundleDeployError, match="verify and publish"):
        deployer._deploy_service_runtime_bundle(
            ssh_service=ssh_service,
            artifact=artifact,
            paths=paths,
        )

    remote_upload = f"{paths.bundle}.upload-{'2' * 32}.tmp"
    assert deployer.events[-1] == (
        "cleanup",
        "cleanup rejected remote runner bundle upload",
        remote_upload,
    )
    steps = [event[1] for event in deployer.events if event[0] in {"run", "write"}]
    assert "clear previous remote runner service" not in steps
    assert "extract remote runner bundle" not in steps
    assert "write remote runner artifact marker" not in steps


def test_partial_upload_failure_attempts_temp_cleanup_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(bundle_module.secrets, "token_hex", lambda _size: "3" * 32)
    artifact = _artifact(tmp_path)
    paths = _paths()
    deployer = Deployer()
    ssh_service = FakeSshService(
        deployer.events,
        upload_error=OSError("connection closed after partial upload"),
    )

    with pytest.raises(OSError, match="partial upload"):
        deployer._deploy_service_runtime_bundle(
            ssh_service=ssh_service,
            artifact=artifact,
            paths=paths,
        )

    remote_upload = f"{paths.bundle}.upload-{'3' * 32}.tmp"
    assert deployer.events[-1] == (
        "cleanup",
        "cleanup rejected remote runner bundle upload",
        remote_upload,
    )
    steps = [event[1] for event in deployer.events if event[0] in {"run", "write"}]
    assert steps == ["prepare remote runner directories"]


def test_each_deployment_uses_a_distinct_remote_upload_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tokens = iter(("4" * 32, "5" * 32))
    monkeypatch.setattr(bundle_module.secrets, "token_hex", lambda _size: next(tokens))
    artifact = _artifact(tmp_path)
    deployer = Deployer()
    ssh_service = FakeSshService(deployer.events)

    for _ in range(2):
        deployer._deploy_service_runtime_bundle(
            ssh_service=ssh_service,
            artifact=artifact,
            paths=_paths(),
        )

    remote_uploads = [event[2] for event in deployer.events if event[0] == "upload"]
    assert remote_uploads == [
        f"/opt/h2o/current/runner bundle.tar.gz.upload-{'4' * 32}.tmp",
        f"/opt/h2o/current/runner bundle.tar.gz.upload-{'5' * 32}.tmp",
    ]
    assert len(set(remote_uploads)) == 2
