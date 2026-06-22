from __future__ import annotations

import os
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.workflow_engine_adapter import SnakemakeEngineAdapter


def test_snakemake_engine_adapter_builds_profiled_dry_run_and_run_commands(tmp_path: Path) -> None:
    snakemake_command = tmp_path / "tooling" / "workflow-env" / "bin" / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    (Path(cfg.release_dir) / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(cfg)
    calls: list[list[str]] = []
    envs: list[dict[str, str]] = []

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        envs.append(dict(_kwargs.get("env") or {}))
        return Result()

    adapter = SnakemakeEngineAdapter(cfg, run_command=fake_run)
    adapter.dry_run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
    )
    adapter.run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
        event_log_path=tmp_path / "logs" / "snakemake-events.jsonl",
    )

    assert calls[0][0] == str(snakemake_command)
    assert "--workflow-profile" in calls[0]
    assert str(Path(cfg.workflow_profile_dir)) in calls[0]
    assert "-n" in calls[0]
    assert "--workflow-profile" in calls[1]
    assert "-n" not in calls[1]
    assert "--show-failed-logs" in calls[1]
    assert "--logger" in calls[1]
    assert "h2ometa" in calls[1]
    assert "--logger-h2ometa-event-path" in calls[1]
    assert str(tmp_path / "logs" / "snakemake-events.jsonl") in calls[1]
    assert str(Path(cfg.release_dir)) in envs[1]["PYTHONPATH"].split(os.pathsep)


def test_snakemake_engine_adapter_passes_live_poll_callback_to_process_runner(monkeypatch, tmp_path: Path) -> None:
    snakemake_command = tmp_path / "snakemake"
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(snakemake_command),
    )
    (Path(cfg.release_dir) / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(cfg)
    poll_calls: list[str] = []
    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run_process(command, **kwargs):
        captured["command"] = list(command)
        captured["on_poll"] = kwargs.get("on_poll")
        callback = kwargs.get("on_poll")
        if callback is not None:
            callback()
        return Result()

    monkeypatch.setattr("apps.remote_runner.workflow_engine_adapter.run_process", fake_run_process)

    adapter = SnakemakeEngineAdapter(cfg)
    adapter.run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
        event_log_path=tmp_path / "logs" / "snakemake-events.jsonl",
        on_poll=lambda: poll_calls.append("poll"),
    )

    assert captured["on_poll"] is not None
    assert poll_calls == ["poll"]
    assert "--logger-h2ometa-event-path" in captured["command"]
