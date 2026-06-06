from __future__ import annotations

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
    )
    adapter.run(
        snakefile=tmp_path / "workflow" / "Snakefile",
        work_dir=tmp_path / "work",
        config_path=tmp_path / "work" / "run-config.json",
    )

    assert calls[0][0] == str(snakemake_command)
    assert "--workflow-profile" in calls[0]
    assert str(Path(cfg.workflow_profile_dir)) in calls[0]
    assert "-n" in calls[0]
    assert "--workflow-profile" in calls[1]
    assert "-n" not in calls[1]
