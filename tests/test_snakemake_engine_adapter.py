from __future__ import annotations

import os
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.workflow_engine_adapter import SnakemakeEngineAdapter, WorkflowRuntimeCommandError


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


def test_snakemake_engine_adapter_builds_explicit_rule_rerun_commands(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    (Path(cfg.release_dir) / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(cfg)
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return Result()

    adapter = SnakemakeEngineAdapter(cfg, run_command=fake_run)
    adapter.dry_run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
        forcerun_rules=["align", "align"],
        rerun_incomplete=True,
        target_paths=[str(tmp_path / "work" / "results" / "summary.tsv")],
    )
    adapter.run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
        event_log_path=tmp_path / "logs" / "snakemake-events.jsonl",
        forcerun_rules=["align"],
        rerun_incomplete=True,
        target_paths=[str(tmp_path / "work" / "results" / "summary.tsv")],
    )

    for command in calls:
        assert "--rerun-incomplete" in command
        assert "--forcerun" in command
        assert command[command.index("--forcerun") + 1] == "align"
        assert command.count("align") == 1
        assert "--forceall" not in command
        assert "--touch" not in command
        assert "--ignore-incomplete" not in command
        assert command[-1] == str(tmp_path / "work" / "results" / "summary.tsv")
    assert "-n" in calls[0]
    assert "-n" not in calls[1]
    assert "--logger-h2ometa-event-path" in calls[1]


def test_snakemake_engine_adapter_rejects_unsafe_forcerun_rule_names(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    (Path(cfg.release_dir) / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(cfg)
    adapter = SnakemakeEngineAdapter(cfg, run_command=lambda *_args, **_kwargs: None)

    try:
        adapter.dry_run(
            snakefile=tmp_path / "workflow" / "Snakefile",
            work_dir=tmp_path / "work",
            config_path=tmp_path / "work" / "run-config.json",
            forcerun_rules=["align;rm"],
        )
    except WorkflowRuntimeCommandError as exc:
        assert "SNAKEMAKE_FORCERUN_RULE_INVALID" in str(exc)
    else:
        raise AssertionError("Unsafe rule name was accepted")


def test_snakemake_engine_adapter_rejects_flag_like_targets(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        token="phase2-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(tmp_path / "release"),
        snakemake_command=str(tmp_path / "snakemake"),
    )
    (Path(cfg.release_dir) / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    ensure_runtime_layout(cfg)
    adapter = SnakemakeEngineAdapter(cfg, run_command=lambda *_args, **_kwargs: None)

    try:
        adapter.dry_run(
            snakefile=tmp_path / "workflow" / "Snakefile",
            work_dir=tmp_path / "work",
            config_path=tmp_path / "work" / "run-config.json",
            target_paths=["--touch"],
        )
    except WorkflowRuntimeCommandError as exc:
        assert "SNAKEMAKE_TARGET_PATH_INVALID" in str(exc)
    else:
        raise AssertionError("Flag-like target path was accepted")


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
