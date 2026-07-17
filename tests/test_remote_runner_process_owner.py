from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace

import pytest

from apps.remote_runner import process_owner
from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_process_lifetime import (
    RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
)
from core.contracts.runner_process_owner import (
    RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
    RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
    RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS,
    runner_process_owner_canonical_json,
    runner_process_owner_fingerprint,
)


_LAUNCH_ID = "1" * 32
_OTHER_LAUNCH_ID = "2" * 32
_BOOT_ID = "11111111-2222-3333-4444-555555555555"
_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64
_HASH_C = "sha256:" + "c" * 64
_HASH_D = "sha256:" + "d" * 64


def _cfg(*, runtime_state_path: str = "/shared/runtime/runner-state.json"):
    return SimpleNamespace(
        service_name="h2ometa-remote",
        version="owner-test-v5",
        mode="background_process",
        runtime_state_path=runtime_state_path,
    )


def _incarnation(*, pid: int = 123) -> dict[str, object]:
    return build_linux_process_incarnation(
        boot_id=_BOOT_ID,
        pid=pid,
        proc_start_ticks=777,
    )


def _startup_binding(*, persisted: str = _HASH_A) -> dict[str, object]:
    return {
        "artifactArchiveSha256Path": "/runner/releases/v5/artifact.sha256",
        "bootstrapManifestFingerprint": _HASH_C,
        "configPath": "/runner/shared/config/runner.json",
        "declaredArtifactArchiveSha256": _HASH_D,
        "effectiveConfigFingerprint": _HASH_B,
        "manifestPath": "/runner/releases/v5/bootstrap_manifest.json",
        "packagePath": "/runner/releases/v5/remote_runner",
        "persistedConfigFingerprint": persisted,
        "protocolFingerprint": "sha256:" + "e" * 64,
        "protocolVersion": "runner-protocol.v5",
        "runnerPythonPath": "/runner/releases/v5/runtime/bin/python",
    }


class _FakeLock:
    def __init__(self, *, inode: int = 901) -> None:
        self.inode = inode

    def describe_identity(self) -> dict[str, object]:
        return {
            "device": 17,
            "inode": self.inode,
            "path": "/shared/runtime/runner.lock",
            "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
        }


def test_invalid_runtime_state_path_maps_all_owner_boundaries_to_exit_75() -> None:
    cfg = _cfg(runtime_state_path="")
    expected_environment = {
        RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV: _LAUNCH_ID,
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV: _HASH_A,
    }

    calls = (
        lambda: process_owner.publish_runner_process_owner(
            cfg,
            startup_binding=_startup_binding(),
            lifetime_lock=_FakeLock(),
            launch_id=_LAUNCH_ID,
            process_incarnation=_incarnation(),
        ),
        lambda: process_owner.adopt_runner_process_owner(
            cfg,
            startup_binding=_startup_binding(),
            lifetime_lock=_FakeLock(),
            environ=expected_environment,
            process_incarnation=_incarnation(),
        ),
        lambda: process_owner.read_runner_process_owner_reference(cfg),
        lambda: process_owner.read_runner_process_owner_record(
            cfg,
            launch_id=_LAUNCH_ID,
        ),
    )

    for call in calls:
        with pytest.raises(process_owner.RunnerProcessOwnerError) as exc_info:
            call()
        assert exc_info.value.exit_status == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS


def test_missing_or_explosive_runtime_state_attribute_maps_owner_reads_to_exit_75() -> None:
    class ExplosiveConfig:
        @property
        def runtime_state_path(self):
            raise RuntimeError("explosive config getter")

    for cfg in (SimpleNamespace(), ExplosiveConfig()):
        for call in (
            lambda: process_owner.read_runner_process_owner_reference(cfg),
            lambda: process_owner.read_runner_process_owner_record(
                cfg,
                launch_id=_LAUNCH_ID,
            ),
        ):
            with pytest.raises(process_owner.RunnerProcessOwnerError) as exc_info:
                call()
            assert (
                exc_info.value.exit_status
                == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
            )


def _owner_exec_helper_source() -> str:
    return textwrap.dedent(
        """
        import os
        from pathlib import Path
        import sys
        import time
        from types import SimpleNamespace

        repo_root, state_path, ready_path, release_path = sys.argv[1:]
        sys.path.insert(0, repo_root)
        from apps.remote_runner.process_lifetime_lock import (
            acquire_runner_process_lifetime_lock,
            adopt_runner_process_lifetime_lock,
        )
        from apps.remote_runner.process_owner import (
            adopt_runner_process_owner,
            build_runner_process_owner_exec_environment,
            publish_runner_process_owner,
        )
        from core.contracts.runner_process_lifetime import (
            RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV,
        )
        from core.contracts.runner_process_owner import (
            RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
            RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
        )

        root = Path(state_path).parents[2]
        release = root / "release"
        cfg = SimpleNamespace(
            service_name="h2ometa-remote",
            version="owner-exec-test",
            mode="background_process",
            runtime_state_path=state_path,
        )
        startup = {
            "artifactArchiveSha256Path": (release / "artifact.sha256").as_posix(),
            "bootstrapManifestFingerprint": "sha256:" + "c" * 64,
            "configPath": (root / "config" / "runner.json").as_posix(),
            "declaredArtifactArchiveSha256": "sha256:" + "d" * 64,
            "effectiveConfigFingerprint": "sha256:" + "b" * 64,
            "manifestPath": (release / "bootstrap_manifest.json").as_posix(),
            "packagePath": (release / "remote_runner").as_posix(),
            "persistedConfigFingerprint": "sha256:" + "a" * 64,
            "protocolFingerprint": "sha256:" + "e" * 64,
            "protocolVersion": "runner-protocol.v5",
            "runnerPythonPath": (release / "runtime" / "bin" / "python").as_posix(),
        }
        if os.environ.get("H2OMETA_OWNER_EXEC_TEST_PHASE") == "adopt":
            lease = adopt_runner_process_lifetime_lock(cfg)
            owner = adopt_runner_process_owner(
                cfg,
                startup_binding=startup,
                lifetime_lock=lease,
            )
            assert RUNNER_PROCESS_LIFETIME_LOCK_FD_ENV not in os.environ
            assert RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV not in os.environ
            assert RUNNER_PROCESS_OWNER_FINGERPRINT_ENV not in os.environ
            Path(ready_path).write_text(
                str(owner["launchId"]) + "\\n", encoding="utf-8"
            )
            deadline = time.monotonic() + 10
            while not Path(release_path).exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("parent did not release owner child")
                time.sleep(0.02)
            lease.release()
        else:
            lease = acquire_runner_process_lifetime_lock(cfg)
            owner = publish_runner_process_owner(
                cfg,
                startup_binding=startup,
                lifetime_lock=lease,
                launch_id="1" * 32,
            )
            environment = lease.build_exec_environment(os.environ)
            environment = build_runner_process_owner_exec_environment(
                owner, environment
            )
            environment["H2OMETA_OWNER_EXEC_TEST_PHASE"] = "adopt"
            executable = sys.executable
            os.execve(
                executable,
                [
                    executable,
                    str(Path(__file__).resolve()),
                    repo_root,
                    state_path,
                    ready_path,
                    release_path,
                ],
                environment,
            )
        """
    )


def test_linux_owner_exec_helper_source_compiles_cross_platform() -> None:
    compile(_owner_exec_helper_source(), "owner_exec_helper.py", "exec")


def test_publish_builds_immutable_record_before_current_reference(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def publish_files(_cfg, **kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(process_owner, "_publish_owner_files", publish_files)

    owner = process_owner.publish_runner_process_owner(
        _cfg(),
        startup_binding=_startup_binding(),
        lifetime_lock=_FakeLock(),
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )

    assert owner["launchId"] == _LAUNCH_ID
    assert owner["phase"] == "launcher-preparation"
    assert owner["startupBinding"]["configuredMode"] == "background_process"
    assert owner["startupBinding"]["bootstrapManifestPath"].endswith(
        "/bootstrap_manifest.json"
    )
    assert owner["lifetimeLock"]["inode"] == 901
    assert captured["launch_id"] == _LAUNCH_ID
    assert captured["owner_payload"] == (
        runner_process_owner_canonical_json(owner) + "\n"
    ).encode("utf-8")
    reference = json.loads(bytes(captured["reference_payload"]).decode("utf-8"))
    assert reference == {
        "launchId": _LAUNCH_ID,
        "ownerFingerprint": runner_process_owner_fingerprint(owner),
        "schemaVersion": RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
    }


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_publication_rejects_inexact_startup_snapshot_fields(
    monkeypatch,
    mutation: str,
) -> None:
    startup = _startup_binding()
    if mutation == "missing":
        startup.pop("manifestPath")
    else:
        startup["futureEvidence"] = _HASH_A
    monkeypatch.setattr(
        process_owner,
        "_publish_owner_files",
        lambda *_args, **_kwargs: pytest.fail("inexact evidence must not publish"),
    )

    with pytest.raises(process_owner.RunnerProcessOwnerError) as exc_info:
        process_owner.publish_runner_process_owner(
            _cfg(),
            startup_binding=startup,
            lifetime_lock=_FakeLock(),
            launch_id=_LAUNCH_ID,
            process_incarnation=_incarnation(),
        )

    assert exc_info.value.exit_status == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS


def test_owner_exec_environment_and_adoption_bind_exact_record(
    monkeypatch,
) -> None:
    cfg = _cfg()
    lock = _FakeLock()
    monkeypatch.setattr(process_owner, "_publish_owner_files", lambda *_a, **_k: None)
    owner = process_owner.publish_runner_process_owner(
        cfg,
        startup_binding=_startup_binding(),
        lifetime_lock=lock,
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )
    fingerprint = runner_process_owner_fingerprint(owner)
    environment = process_owner.build_runner_process_owner_exec_environment(
        owner,
        {"KEEP": "yes"},
    )
    assert environment == {
        "KEEP": "yes",
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV: fingerprint,
        RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV: _LAUNCH_ID,
    }

    monkeypatch.setattr(
        process_owner,
        "_read_current_owner_reference",
        lambda _cfg: {
            "launchId": _LAUNCH_ID,
            "ownerFingerprint": fingerprint,
            "schemaVersion": RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
        },
    )
    monkeypatch.setattr(
        process_owner,
        "_read_owner_record",
        lambda _cfg, *, launch_id: owner,
    )
    monkeypatch.setenv(RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV, _LAUNCH_ID)
    monkeypatch.setenv(RUNNER_PROCESS_OWNER_FINGERPRINT_ENV, fingerprint)

    adopted = process_owner.adopt_runner_process_owner(
        cfg,
        startup_binding=_startup_binding(),
        lifetime_lock=lock,
        process_incarnation=_incarnation(),
    )

    assert adopted == owner
    assert RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV not in os.environ
    assert RUNNER_PROCESS_OWNER_FINGERPRINT_ENV not in os.environ


@pytest.mark.parametrize("drift", ["pointer", "config", "incarnation", "lock"])
def test_adoption_fails_closed_on_any_owner_binding_drift(
    monkeypatch,
    drift: str,
) -> None:
    cfg = _cfg()
    owner = process_owner.publish_runner_process_owner
    monkeypatch.setattr(process_owner, "_publish_owner_files", lambda *_a, **_k: None)
    published = owner(
        cfg,
        startup_binding=_startup_binding(),
        lifetime_lock=_FakeLock(),
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )
    fingerprint = runner_process_owner_fingerprint(published)
    reference_fingerprint = _HASH_A if drift == "pointer" else fingerprint
    monkeypatch.setattr(
        process_owner,
        "_read_current_owner_reference",
        lambda _cfg: {
            "launchId": _LAUNCH_ID,
            "ownerFingerprint": reference_fingerprint,
            "schemaVersion": RUNNER_PROCESS_OWNER_REFERENCE_SCHEMA,
        },
    )
    monkeypatch.setattr(
        process_owner,
        "_read_owner_record",
        lambda _cfg, *, launch_id: published,
    )
    environment = {
        RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV: _LAUNCH_ID,
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV: fingerprint,
    }
    startup = _startup_binding(
        persisted=_HASH_B if drift == "config" else _HASH_A
    )
    incarnation = _incarnation(pid=124 if drift == "incarnation" else 123)
    lock = _FakeLock(inode=902 if drift == "lock" else 901)

    with pytest.raises(process_owner.RunnerProcessOwnerError) as exc_info:
        process_owner.adopt_runner_process_owner(
            cfg,
            startup_binding=startup,
            lifetime_lock=lock,
            environ=environment,
            process_incarnation=incarnation,
        )

    assert exc_info.value.exit_status == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS


def test_capture_failure_precedes_any_owner_file_publication(monkeypatch) -> None:
    monkeypatch.setattr(
        process_owner,
        "capture_linux_process_incarnation",
        lambda: (_ for _ in ()).throw(RuntimeError("procfs unavailable")),
    )
    monkeypatch.setattr(
        process_owner,
        "_publish_owner_files",
        lambda *_args, **_kwargs: pytest.fail("files must follow procfs capture"),
    )

    with pytest.raises(process_owner.RunnerProcessOwnerError) as exc_info:
        process_owner.publish_runner_process_owner(
            _cfg(),
            startup_binding=_startup_binding(),
            lifetime_lock=_FakeLock(),
            launch_id=_LAUNCH_ID,
        )

    assert exc_info.value.exit_status == RUNNER_PROCESS_OWNER_UNAVAILABLE_EXIT_STATUS
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.skipif(sys.platform != "linux", reason="secure dirfd I/O is Linux only")
def test_real_owner_records_are_immutable_and_pointer_advances(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "shared" / "runtime"
    runtime_dir.mkdir(parents=True, mode=0o700)
    cfg = _cfg(runtime_state_path=str(runtime_dir / "runner-state.json"))
    lock_path = runtime_dir / "runner.lock"
    lock_path.write_text("", encoding="utf-8")
    lock_stat = lock_path.stat()

    class RealPathLock:
        def describe_identity(self) -> dict[str, object]:
            return {
                "device": lock_stat.st_dev,
                "inode": lock_stat.st_ino,
                "path": lock_path.as_posix(),
                "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
            }

    startup = _real_startup_binding(tmp_path)
    first = process_owner.publish_runner_process_owner(
        cfg,
        startup_binding=startup,
        lifetime_lock=RealPathLock(),
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )
    first_path = process_owner.get_runner_process_owner_record_path(
        cfg,
        _LAUNCH_ID,
    )
    first_bytes = first_path.read_bytes()
    second = process_owner.publish_runner_process_owner(
        cfg,
        startup_binding=startup,
        lifetime_lock=RealPathLock(),
        launch_id=_OTHER_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )

    assert first_path.read_bytes() == first_bytes
    assert stat.S_IMODE(first_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(
        process_owner.get_runner_process_owner_directory(cfg).stat().st_mode
    ) == 0o700
    assert process_owner.read_runner_process_owner_record(
        cfg,
        launch_id=_LAUNCH_ID,
    ) == first
    assert process_owner.read_runner_process_owner_record(
        cfg,
        launch_id=_OTHER_LAUNCH_ID,
    ) == second
    assert process_owner.read_runner_process_owner_reference(cfg)[
        "launchId"
    ] == _OTHER_LAUNCH_ID


@pytest.mark.skipif(sys.platform != "linux", reason="secure dirfd I/O is Linux only")
def test_real_owner_record_never_overwrites_same_launch_id(tmp_path: Path) -> None:
    cfg, startup, lock = _real_storage_inputs(tmp_path)
    first = process_owner.publish_runner_process_owner(
        cfg,
        startup_binding=startup,
        lifetime_lock=lock,
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )
    record_path = process_owner.get_runner_process_owner_record_path(cfg, _LAUNCH_ID)
    before = record_path.read_bytes()

    with pytest.raises(process_owner.RunnerProcessOwnerError):
        process_owner.publish_runner_process_owner(
            cfg,
            startup_binding=startup,
            lifetime_lock=lock,
            launch_id=_LAUNCH_ID,
            process_incarnation=_incarnation(pid=124),
        )

    assert record_path.read_bytes() == before
    assert process_owner.read_runner_process_owner_record(
        cfg,
        launch_id=_LAUNCH_ID,
    ) == first


@pytest.mark.skipif(sys.platform != "linux", reason="secure dir modes are Linux only")
def test_real_owner_record_read_rejects_owner_directory_mode_drift(
    tmp_path: Path,
) -> None:
    cfg, startup, lock = _real_storage_inputs(tmp_path)
    process_owner.publish_runner_process_owner(
        cfg,
        startup_binding=startup,
        lifetime_lock=lock,
        launch_id=_LAUNCH_ID,
        process_incarnation=_incarnation(),
    )
    owner_directory = process_owner.get_runner_process_owner_directory(cfg)
    owner_directory.chmod(0o755)
    try:
        with pytest.raises(process_owner.RunnerProcessOwnerError):
            process_owner.read_runner_process_owner_record(
                cfg,
                launch_id=_LAUNCH_ID,
            )
    finally:
        owner_directory.chmod(0o700)


@pytest.mark.skipif(sys.platform != "linux", reason="secure dirfd I/O is Linux only")
def test_real_pointer_rejects_symlink_without_touching_victim(tmp_path: Path) -> None:
    cfg, startup, lock = _real_storage_inputs(tmp_path)
    victim = tmp_path / "victim"
    victim.write_text("unchanged", encoding="utf-8")
    pointer = process_owner.get_runner_process_owner_pointer_path(cfg)
    pointer.symlink_to(victim)

    with pytest.raises(process_owner.RunnerProcessOwnerError):
        process_owner.publish_runner_process_owner(
            cfg,
            startup_binding=startup,
            lifetime_lock=lock,
            launch_id=_LAUNCH_ID,
            process_incarnation=_incarnation(),
        )

    assert victim.read_text(encoding="utf-8") == "unchanged"
    assert pointer.is_symlink()
    assert process_owner.get_runner_process_owner_record_path(
        cfg,
        _LAUNCH_ID,
    ).is_file()


@pytest.mark.skipif(sys.platform != "linux", reason="requires Linux flock/exec/procfs")
def test_real_owner_record_survives_exec_and_binds_adopted_process(
    tmp_path: Path,
) -> None:
    from apps.remote_runner import process_lifetime_lock

    state_path = tmp_path / "shared" / "runtime" / "runner-state.json"
    ready_path = tmp_path / "owner-ready"
    release_path = tmp_path / "release-owner"
    helper_path = tmp_path / "owner_exec_helper.py"
    repo_root = Path(__file__).resolve().parents[1]
    helper_path.write_text(_owner_exec_helper_source(), encoding="utf-8")
    environment = dict(os.environ)
    for key in (
        "H2OMETA_OWNER_EXEC_TEST_PHASE",
        RUNNER_PROCESS_OWNER_FINGERPRINT_ENV,
        RUNNER_PROCESS_OWNER_LAUNCH_ID_ENV,
    ):
        environment.pop(key, None)
    process = subprocess.Popen(
        [
            sys.executable,
            str(helper_path),
            str(repo_root),
            str(state_path),
            str(ready_path),
            str(release_path),
        ],
        env=environment,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    cfg = _cfg(runtime_state_path=str(state_path))
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.02)
        assert ready_path.read_text(encoding="utf-8") == f"{_LAUNCH_ID}\n"
        owner = process_owner.read_runner_process_owner_record(
            cfg,
            launch_id=_LAUNCH_ID,
        )
        assert owner["processIncarnation"]["pid"] == process.pid
        assert process_owner.read_runner_process_owner_reference(cfg)[
            "ownerFingerprint"
        ] == runner_process_owner_fingerprint(owner)
        with pytest.raises(
            process_lifetime_lock.RunnerProcessLifetimeLockError
        ) as exc_info:
            process_lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        assert (
            exc_info.value.reason_code
            == process_lifetime_lock.RUNNER_PROCESS_LIFETIME_LOCK_HELD
        )

        release_path.write_text("release\n", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
        replacement = process_lifetime_lock.acquire_runner_process_lifetime_lock(cfg)
        replacement.release()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _real_storage_inputs(tmp_path: Path):
    runtime_dir = tmp_path / "shared" / "runtime"
    runtime_dir.mkdir(parents=True, mode=0o700)
    cfg = _cfg(runtime_state_path=str(runtime_dir / "runner-state.json"))
    lock_path = runtime_dir / "runner.lock"
    lock_path.write_text("", encoding="utf-8")
    lock_stat = lock_path.stat()

    class RealPathLock:
        def describe_identity(self) -> dict[str, object]:
            return {
                "device": lock_stat.st_dev,
                "inode": lock_stat.st_ino,
                "path": lock_path.as_posix(),
                "profile": RUNNER_PROCESS_LIFETIME_LOCK_PROFILE,
            }

    return cfg, _real_startup_binding(tmp_path), RealPathLock()


def _real_startup_binding(tmp_path: Path) -> dict[str, object]:
    release = tmp_path / "runner" / "releases" / "v5"
    return {
        "artifactArchiveSha256Path": (release / "artifact.sha256").as_posix(),
        "bootstrapManifestFingerprint": _HASH_C,
        "configPath": (tmp_path / "runner" / "shared" / "config" / "runner.json").as_posix(),
        "declaredArtifactArchiveSha256": _HASH_D,
        "effectiveConfigFingerprint": _HASH_B,
        "manifestPath": (release / "bootstrap_manifest.json").as_posix(),
        "packagePath": (release / "remote_runner").as_posix(),
        "persistedConfigFingerprint": _HASH_A,
        "protocolFingerprint": "sha256:" + "e" * 64,
        "protocolVersion": "runner-protocol.v5",
        "runnerPythonPath": (release / "runtime" / "bin" / "python").as_posix(),
    }
