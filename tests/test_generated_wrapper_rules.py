from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from apps.remote_runner.storage import upsert_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="wrapper-rule-token",
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


def _input(tmp_path: Path) -> list[dict[str, str]]:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@r1\nACGT\n+\nFFFF\n", encoding="utf-8")
    return [{"path": str(reads), "role": "input", "filename": "reads.fastq"}]


def test_generated_workflow_uses_rule_spec_draft_template(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::draft-rule",
            "name": "draft-rule",
            "source": "conda-forge",
            "packageSpec": "conda-forge::draft-rule=1.0",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "conda-package",
                "ruleTemplate": {
                    "commandTemplate": "wc -l {input.reads:q} > {output.report:q}",
                    "inputs": [{"name": "reads", "type": "file", "required": True}],
                    "outputs": [{"name": "report", "path": "draft-report.txt", "kind": "log", "mimeType": "text/plain"}],
                },
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_draft_rule",
        request_id="req_draft_rule",
        run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "conda-forge::draft-rule"}},
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = (tmp_path / "work" / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    assert "wc -l" in snakefile
    assert run_config["tool"]["ruleTemplate"]["commandTemplate"] == "wc -l {input.reads:q} > {output.report:q}"
    assert run_config["tool"]["ruleSpecDraft"]["source"] == "conda-package"


def test_generated_workflow_renders_snakemake_wrapper_rule(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "bioconda::fastqc-wrapper",
            "name": "fastqc-wrapper",
            "source": "bioconda",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "wrapper": "v9.8.0/bio/fastqc",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [{"name": "html", "path": "fastqc.html", "kind": "html", "mimeType": "text/html"}],
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_wrapper_rule",
        request_id="req_wrapper_rule",
        run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "bioconda::fastqc-wrapper"}},
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = (tmp_path / "work" / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    assert "wrapper:" in snakefile
    assert "'v9.8.0/bio/fastqc'" in snakefile
    assert "shell:" not in snakefile
    assert "conda:" not in snakefile
    assert run_config["tool"]["ruleTemplate"]["wrapper"] == "v9.8.0/bio/fastqc"


def test_generated_workflow_preserves_rule_spec_provenance(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "bioconda::fastqc-wrapper",
            "name": "fastqc-wrapper",
            "source": "bioconda",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "snakemake-wrapper",
                "lock": {
                    "type": "snakemake-wrapper",
                    "wrapperRepository": "snakemake/snakemake-wrappers",
                    "wrapperRef": "v9.8.0",
                    "wrapperPath": "bio/fastqc",
                    "wrapperIdentifier": "v9.8.0/bio/fastqc",
                    "packageSpec": "bioconda::fastqc=0.12.1",
                    "version": "0.12.1",
                },
                "ruleTemplate": {
                    "wrapper": "v9.8.0/bio/fastqc",
                    "inputs": [{"name": "reads", "type": "file", "required": True}],
                    "outputs": [{"name": "html", "path": "fastqc.html", "kind": "html", "mimeType": "text/html"}],
                },
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_wrapper_provenance",
        request_id="req_wrapper_provenance",
        run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "bioconda::fastqc-wrapper"}},
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    tool_config = run_config["tool"]
    assert tool_config["ruleSpecDraft"]["lock"]["wrapperIdentifier"] == "v9.8.0/bio/fastqc"
    assert tool_config["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert tool_config["ruleProvenance"] == {
        "source": "snakemake-wrapper",
        "lockType": "snakemake-wrapper",
        "wrapperRef": "v9.8.0",
        "wrapperPath": "bio/fastqc",
        "wrapperIdentifier": "v9.8.0/bio/fastqc",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "version": "0.12.1",
    }


def test_generated_workflow_provenance_follows_executed_rule_template(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::stored-rule",
            "name": "stored-rule",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "wc -c {input.reads:q} > {output.report:q}",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "stored-report.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_stored_rule",
        request_id="req_stored_rule",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "tool": {
                "id": "conda-forge::stored-rule",
                "ruleSpecDraft": {
                    "source": "snakemake-wrapper",
                    "lock": {"type": "snakemake-wrapper", "wrapperIdentifier": "v9.8.0/bio/fastqc"},
                    "ruleTemplate": {
                        "wrapper": "v9.8.0/bio/fastqc",
                        "inputs": [{"name": "reads", "type": "file", "required": True}],
                        "outputs": [{"name": "html", "path": "fastqc.html"}],
                    },
                },
            },
        },
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = (tmp_path / "work" / "workflow" / "Snakefile").read_text(encoding="utf-8")
    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    assert "wc -c" in snakefile
    assert "wrapper:" not in snakefile
    assert run_config["tool"]["ruleTemplate"]["commandTemplate"] == "wc -c {input.reads:q} > {output.report:q}"
    assert "ruleSpecDraft" not in run_config["tool"]
    assert "ruleProvenance" not in run_config["tool"]


def test_generated_workflow_wrapper_provenance_distinguishes_declared_dependency(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "bioconda::wrapper-without-package-lock",
            "name": "wrapper-without-package-lock",
            "source": "bioconda",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "snakemake-wrapper",
                "lock": {
                    "type": "snakemake-wrapper",
                    "wrapperRef": "v9.8.0",
                    "wrapperPath": "bio/fastqc",
                    "wrapperIdentifier": "v9.8.0/bio/fastqc",
                },
                "ruleTemplate": {
                    "wrapper": "v9.8.0/bio/fastqc",
                    "inputs": [{"name": "reads", "type": "file", "required": True}],
                    "outputs": [{"name": "html", "path": "fastqc.html", "kind": "html", "mimeType": "text/html"}],
                },
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_wrapper_declared_dependency",
        request_id="req_wrapper_declared_dependency",
        run_spec={"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "bioconda::wrapper-without-package-lock"}},
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    run_config = json.loads((tmp_path / "work" / "run-config.json").read_text(encoding="utf-8"))
    provenance = run_config["tool"]["ruleProvenance"]
    assert provenance["wrapperIdentifier"] == "v9.8.0/bio/fastqc"
    assert "packageSpec" not in provenance
    assert provenance["declaredPackageSpec"] == "bioconda::fastqc=0.12.1"
