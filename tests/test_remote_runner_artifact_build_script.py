from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.contracts.runner_activation_release_bootstrap_manifest import (
    require_runner_activation_release_bootstrap_manifest,
)
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields
from scripts import build_remote_runner_artifact_on_server as builder


def test_dirty_source_release_files_include_untracked_modules(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    local_dir = repo_root / "apps" / "remote_runner"
    local_dir.mkdir(parents=True)
    tracked = local_dir / "tools.py"
    untracked = local_dir / "tool_contract.py"
    ignored_test = local_dir / "pipelines" / "demo" / ".test" / "fixture.py"
    pipeline_contract = local_dir / "pipelines" / "demo" / ".test" / "run-config.json"
    tracked.write_text("# tracked\n", encoding="utf-8")
    untracked.write_text("# untracked\n", encoding="utf-8")
    ignored_test.parent.mkdir(parents=True)
    ignored_test.write_text("# ignored\n", encoding="utf-8")
    pipeline_contract.write_text("{}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if "--others" in cmd:
            return SimpleNamespace(stdout="apps/remote_runner/tool_contract.py\napps/remote_runner/pipelines/demo/.test/fixture.py\n")
        return SimpleNamespace(stdout="apps/remote_runner/tools.py\napps/remote_runner/pipelines/demo/.test/run-config.json\n")

    monkeypatch.setattr(builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    files = builder.git_tracked_release_files(local_dir, include_untracked=True)

    assert tracked in files
    assert untracked in files
    assert pipeline_contract in files
    assert ignored_test not in files
    assert any("--others" in call for call in calls)


@pytest.mark.parametrize("include_untracked", [False, True])
def test_release_source_collection_rejects_native_payloads(
    monkeypatch,
    tmp_path: Path,
    include_untracked: bool,
) -> None:
    repo_root = tmp_path
    local_dir = repo_root / "apps" / "remote_runner"
    payload = local_dir / "_unapproved.abi3.so"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"ELF")

    def fake_run(cmd, **_kwargs):
        is_untracked_query = "--others" in cmd
        selected = is_untracked_query if include_untracked else not is_untracked_query
        return SimpleNamespace(
            stdout="apps/remote_runner/_unapproved.abi3.so\n" if selected else ""
        )

    monkeypatch.setattr(builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(builder.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="unapproved native payload"):
        builder.git_tracked_release_files(
            local_dir,
            include_untracked=include_untracked,
        )


def test_release_source_collection_rejects_symbolic_links(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    local_dir = repo_root / "apps" / "remote_runner"
    payload = local_dir / "linked.py"
    payload.parent.mkdir(parents=True)
    payload.write_text("target", encoding="utf-8")
    path_type = type(payload)
    original_is_symlink = path_type.is_symlink

    monkeypatch.setattr(
        path_type,
        "is_symlink",
        lambda self: self == payload or original_is_symlink(self),
    )
    monkeypatch.setattr(builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        lambda cmd, **_kwargs: SimpleNamespace(
            stdout="apps/remote_runner/linked.py\n" if "--others" in cmd else ""
        ),
    )

    with pytest.raises(RuntimeError, match="unapproved link"):
        builder.git_tracked_release_files(local_dir, include_untracked=True)


def test_release_source_collection_rejects_native_magic(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    local_dir = repo_root / "apps" / "remote_runner"
    payload = local_dir / "owner.py"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"\x7fELFfake")

    monkeypatch.setattr(builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        builder.subprocess,
        "run",
        lambda cmd, **_kwargs: SimpleNamespace(
            stdout="apps/remote_runner/owner.py\n" if "--others" not in cmd else ""
        ),
    )

    with pytest.raises(RuntimeError, match="unapproved native payload"):
        builder.git_tracked_release_files(local_dir)


def test_remote_runner_source_upload_includes_shared_contracts(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "apps" / "remote_runner").mkdir(parents=True)
    (repo_root / "core" / "contracts").mkdir(parents=True)
    (repo_root / "core" / "__init__.py").write_text("", encoding="utf-8")

    calls: list[tuple[str, str, str, bool]] = []

    def fake_upload_tree(sftp, local_dir: Path, remote_dir: str, *, include_untracked: bool = False) -> None:
        calls.append(("tree", local_dir.relative_to(repo_root).as_posix(), remote_dir, include_untracked))

    def fake_upload_file(sftp, local_file: Path, remote_file: str) -> None:
        calls.append(("file", local_file.relative_to(repo_root).as_posix(), remote_file, False))

    monkeypatch.setattr(builder, "REPO_ROOT", repo_root)
    monkeypatch.setattr(builder, "upload_tree", fake_upload_tree)
    monkeypatch.setattr(builder, "upload_file", fake_upload_file)

    builder.upload_remote_runner_sources(object(), "/tmp/h2ometa-build", include_untracked=True)

    assert calls == [
        ("tree", "apps/remote_runner", "/tmp/h2ometa-build/bundle/remote_runner", True),
        ("file", "core/__init__.py", "/tmp/h2ometa-build/bundle/core/__init__.py", False),
        ("file", "core/async_boundary.py", "/tmp/h2ometa-build/bundle/core/async_boundary.py", False),
        ("file", "core/api_payloads.py", "/tmp/h2ometa-build/bundle/core/api_payloads.py", False),
        ("file", "core/api_responses.py", "/tmp/h2ometa-build/bundle/core/api_responses.py", False),
        ("file", "core/logging_config.py", "/tmp/h2ometa-build/bundle/core/logging_config.py", False),
        ("file", "core/problem_responses.py", "/tmp/h2ometa-build/bundle/core/problem_responses.py", False),
        ("file", "core/problem_status.py", "/tmp/h2ometa-build/bundle/core/problem_status.py", False),
        ("tree", "core/contracts", "/tmp/h2ometa-build/bundle/core/contracts", True),
    ]


def test_remote_build_script_embeds_exact_runner_protocol_descriptor() -> None:
    fields = build_runner_protocol_manifest_fields()

    plan = builder.build_remote_script_plan(
        version="protocol-test",
        platform="linux-64",
        runtime_source="copy-from-current",
    )

    assert '"runnerProtocol"' in plan["remoteScript"]
    assert str(fields["runnerProtocolFingerprint"]) in plan["remoteScript"]


def test_remote_build_script_uses_exact_bootstrap_contract_and_external_build_metadata() -> None:
    manifest = builder.build_bootstrap_manifest(
        version="protocol-test",
        platform="linux-64",
    )
    plan = builder.build_remote_script_plan(
        version="protocol-test",
        platform="linux-64",
        runtime_source="lockfile",
        lock_file_name="explicit.txt",
        lock_sha256="a" * 64,
    )

    assert require_runner_activation_release_bootstrap_manifest(manifest) == manifest
    assert set(manifest) == {
        "platform",
        "runnerProtocol",
        "runnerProtocolFingerprint",
        "runtime",
        "service",
        "version",
    }
    assert '"build"' not in plan["remoteScript"]
    assert plan["lockFile"] == "explicit.txt"
    assert plan["lockSha256"] == "a" * 64
    assert 'find "$BUILD_ROOT/bundle" -type d -exec chmod 755 {} +' in plan[
        "remoteScript"
    ]
    assert 'find "$BUILD_ROOT/bundle" -type f -perm /111 -exec chmod 755 {} +' in (
        plan["remoteScript"]
    )
    assert 'find "$BUILD_ROOT/bundle" -type f ! -perm /111 -exec chmod 644 {} +' in (
        plan["remoteScript"]
    )
    script = plan["remoteScript"]
    deterministic_archive_command = (
        "tar --format=ustar --sort=name --owner=0 --group=0 --numeric-owner "
        '--mtime=@0 -cf - -C "$BUILD_ROOT/bundle" . | gzip -n > '
        f'{plan["artifactName"]}'
    )
    assert script.index("set -euo pipefail") < script.index("umask 077")
    assert deterministic_archive_command in script
    assert "tar -czf" not in script


@pytest.mark.parametrize(
    ("version", "platform"),
    [("../invalid", "linux-64"), ("protocol-test", "win-64")],
)
def test_remote_build_script_rejects_invalid_bootstrap_identity(
    version: str,
    platform: str,
) -> None:
    with pytest.raises(ValueError):
        builder.build_bootstrap_manifest(version=version, platform=platform)


def test_remote_build_script_delegates_lifetime_startup_without_bytecode_writes() -> None:
    plan = builder.build_remote_script_plan(
        version="protocol-test",
        platform="linux-64",
        runtime_source="copy-from-current",
    )

    script = plan["remoteScript"]
    assert (
        'exec "$RUNNER_PYTHON" -B -m remote_runner.runner_lifetime_launcher'
        in script
    )
    assert script.index("require_runner_protocol_startup_preflight") < script.index(
        "nohup"
    )
    launch_script = script.split(
        "cat > \"$BUILD_ROOT/bundle/launch_remote_runner.sh\" <<'SH'", maxsplit=1
    )[1].split("\nSH\n", maxsplit=1)[0]
    start_script = script.split(
        "cat > \"$BUILD_ROOT/bundle/start_service.sh\" <<'SH'", maxsplit=1
    )[1].split("\nSH\n", maxsplit=1)[0]
    assert (
        'exec "$RUNNER_PYTHON" -B -m remote_runner.run'
        not in launch_script.splitlines()
    )
    assert "conda-unpack" not in launch_script
    assert "require_runner_protocol_startup_preflight" not in launch_script
    assert 'echo $! > "$RUN_DIR/runner.pid"' not in start_script
    assert "Type=simple" in script
    assert "Restart=on-failure" in script
    assert "RestartPreventExitStatus=73 74 75" in script
    assert "H2OMETA_REMOTE_RUNNER_PYTHON" not in script
