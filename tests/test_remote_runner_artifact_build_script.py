from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
