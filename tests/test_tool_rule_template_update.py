from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool, update_registered_tool_rule_template


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    cfg = RemoteRunnerConfig(
        token="phase-tool-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )
    ensure_runtime_layout(cfg)
    return cfg


def _add_fastq_tool(cfg: RemoteRunnerConfig) -> dict:
    return add_registered_tool(
        cfg,
        {
            "id": "bioconda::fastq",
            "name": "fastq",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.12.1",
            "packageSpec": "bioconda::fastq=0.12.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "summary": "FASTQ toolbox",
            "ruleSpecDraft": {
                "source": "conda-package",
                "requiresUserCompletion": True,
                "ruleTemplate": {"commandTemplate": "old {input.primary:q} > {output.report:q}"},
            },
        },
    )


def test_update_registered_tool_rule_template_promotes_rulespec_to_manifest(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _add_fastq_tool(cfg)

    saved = update_registered_tool_rule_template(
        cfg,
        "bioconda::fastq",
        {
            "commandTemplate": "fastq stats {input.reads:q} --min-q {params.min_quality} > {output.report:q}",
            "inputs": [{"name": "reads", "type": "file", "required": True, "kind": "sequence"}],
            "outputs": [
                {
                    "name": "report",
                    "path": "qc/fastq-report.txt",
                    "kind": "qc-report",
                    "mimeType": "text/plain",
                    "protected": True,
                }
            ],
            "params": {"min_quality": {"type": "integer", "default": 20}},
            "resources": {"threads": {"default": 2}, "mem_mb": {"default": 1024}},
            "log": "logs/fastq.log",
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["bioconda::fastq=0.12.1"],
                }
            },
        },
    )

    template = saved["ruleTemplate"]
    assert template["commandTemplate"] == "fastq stats {input.reads:q} --min-q {params.min_quality} > {output.report:q}"
    assert template["inputs"] == [{"name": "reads", "type": "file", "required": True, "kind": "sequence"}]
    assert template["outputs"][0]["protected"] is True
    assert template["threads"] == 2
    assert template["schedulerResources"] == {"mem_mb": 1024}
    assert template["log"] == "logs/fastq.log"
    assert template["environment"]["conda"]["dependencies"] == ["bioconda::fastq=0.12.1"]
    assert saved["ruleSpecDraft"] == {}
    assert saved["message"] == "RuleSpec saved."

    fetched = fetch_tool(cfg, "bioconda::fastq")
    assert fetched is not None
    assert fetched["ruleTemplate"] == template
    assert fetched["packageSpec"] == "bioconda::fastq=0.12.1"


def test_update_registered_tool_rule_template_requires_existing_tool_and_valid_tokens(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)

    try:
        update_registered_tool_rule_template(cfg, "bioconda::missing", {"commandTemplate": "echo ok"})
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_NOT_FOUND"
    else:
        raise AssertionError("RuleSpec update must not create a missing tool")

    _add_fastq_tool(cfg)
    try:
        update_registered_tool_rule_template(
            cfg,
            "bioconda::fastq",
            {
                "commandTemplate": "fastq stats {input.reads:q} --min-q {params.min_quality} > {output.report:q}",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "report", "mimeType": "text/plain"}],
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_TOKEN_UNSUPPORTED: {params.min_quality}"
    else:
        raise AssertionError("RuleSpec update must validate commandTemplate tokens")
