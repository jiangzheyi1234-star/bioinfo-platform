from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.rule_environment import render_rule_conda_env_yaml
from apps.remote_runner.storage import fetch_tool, persist_upload, upsert_tool
from apps.remote_runner.tools import add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="rule-environment-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(tmp_path / "workflow-env" / "bin" / "conda"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
    )


def _register_multi_dependency_tool(cfg: RemoteRunnerConfig) -> dict:
    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::fastp-rule",
            "name": "fastp",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.23.4",
            "packageSpec": "bioconda::fastp=0.23.4",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf ok > {output.clean_reads:q}",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [{"name": "clean_reads", "path": "clean.fastq.gz", "kind": "sequence", "mimeType": "application/gzip"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/fastp-rule.log",
                "smokeTest": {"inputs": {"reads": {"filename": "reads.fastq", "content": "@r1\nACGT\n+\nFFFF\n"}}},
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda", "conda-forge"],
                        "dependencies": ["bioconda::fastp=0.23.4", "conda-forge::pigz=2.8"],
                    }
                },
            },
        },
    )
    saved["contractStatus"] = {
        "dryRun": {"status": "passed", "message": "Snakemake dry-run passed."},
        "smokeRun": {"status": "passed", "message": "Snakemake smoke run passed."},
        "outputValidation": {"status": "passed", "message": "Output validation passed."},
    }
    return upsert_tool(cfg, saved)


def test_rule_environment_contract_is_persisted(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = _register_multi_dependency_tool(cfg)
    fetched = fetch_tool(cfg, saved["id"])

    assert fetched is not None
    conda = fetched["ruleTemplate"]["environment"]["conda"]
    assert conda["channels"] == ["conda-forge", "bioconda"]
    assert conda["dependencies"] == ["bioconda::fastp=0.23.4", "conda-forge::pigz=2.8"]


def test_rule_environment_render_rejects_unlocked_dependencies() -> None:
    try:
        render_rule_conda_env_yaml(
            rule_template={
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["fastp"],
                    }
                }
            },
            source="bioconda",
            package_spec="bioconda::fastp=0.23.4",
        )
    except ValueError as exc:
        assert str(exc) == "TOOL_RULE_ENVIRONMENT_DEPENDENCY_LOCK_REQUIRED: fastp"
    else:
        raise AssertionError("generated rule environments must reject unlocked conda dependencies")


def test_generated_rule_environment_writes_multi_dependency_env(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _register_multi_dependency_tool(cfg)
    upload = persist_upload(cfg, filename="reads.fastq", content_base64="QAo=", mime_type="text/plain")

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_rule_environment",
        request_id="req_rule_environment",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.fastq", "role": "input"}],
            "tool": {"id": "bioconda::fastp-rule"},
        },
    )

    work_dir = Path(cfg.work_dir) / "run_rule_environment"
    env_yaml = (work_dir / "workflow" / "envs" / "bioconda_fastp-rule.yaml").read_text(encoding="utf-8")
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))

    assert "  - conda-forge\n  - bioconda\n  - nodefaults\n" in env_yaml
    assert '  - "bioconda::fastp=0.23.4"\n' in env_yaml
    assert '  - "conda-forge::pigz=2.8"\n' in env_yaml
    assert run_config["tool"]["ruleTemplate"]["environment"]["conda"]["dependencies"] == [
        "bioconda::fastp=0.23.4",
        "conda-forge::pigz=2.8",
    ]
