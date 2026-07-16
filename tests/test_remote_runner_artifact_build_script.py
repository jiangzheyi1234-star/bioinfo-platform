from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def test_remote_build_script_starts_protocol_preflight_without_bytecode_writes() -> None:
    plan = builder.build_remote_script_plan(
        version="protocol-test",
        platform="linux-64",
        runtime_source="copy-from-current",
    )

    script = plan["remoteScript"]
    assert 'exec "$RUNNER_PYTHON" -B -m remote_runner.run' in script
    assert script.index("require_runner_protocol_startup_preflight") < script.rindex(
        "conda-unpack"
    )
    assert script.index("require_runner_protocol_startup_preflight") < script.index(
        "nohup"
    )
    assert "H2OMETA_REMOTE_RUNNER_PYTHON" not in script
