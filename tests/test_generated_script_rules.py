from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.tools import ToolRegistryError, normalize_rule_template
from tests.generated_workflow_test_helpers import (
    generated_workflow_node,
    generated_workflow_run_spec,
    prepare_unchecked_generated_tool_workflow as prepare_generated_tool_workflow,
    upsert_ready_tool as upsert_tool,
)


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="script-rule-token",
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


def _upsert_script_tool(
    cfg: RemoteRunnerConfig,
    *,
    tool_id: str,
    script_path: str,
    content: str = "print('ok')\n",
) -> None:
    upsert_tool(
        cfg,
        {
            "id": tool_id,
            "name": tool_id.rsplit("::", 1)[-1],
            "source": "bioconda",
            "packageSpec": "bioconda::python=3.12",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "script": script_path,
                "scriptAssets": [{"path": script_path, "content": content}],
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "report",
                        "path": "report.txt",
                        "kind": "log",
                        "mimeType": "text/plain",
                    }
                ],
            },
        },
    )


def test_rule_template_accepts_script_as_strict_single_action() -> None:
    normalized = normalize_rule_template(
        {
            "script": "scripts/count_reads.py",
            "scriptAssets": [
                {"path": "scripts/count_reads.py", "content": "print('ok')\n"}
            ],
            "inputs": [{"name": "reads", "type": "file", "required": True}],
            "outputs": [
                {
                    "name": "report",
                    "path": "report.txt",
                    "kind": "log",
                    "mimeType": "text/plain",
                }
            ],
        },
        required=True,
    )

    assert normalized["script"] == "scripts/count_reads.py"
    assert normalized["scriptAssets"] == [
        {"path": "scripts/count_reads.py", "content": "print('ok')\n"}
    ]
    assert "commandTemplate" not in normalized
    assert "wrapper" not in normalized


def test_rule_template_rejects_script_without_matching_asset() -> None:
    try:
        normalize_rule_template(
            {
                "script": "scripts/count_reads.py",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "report",
                        "path": "report.txt",
                        "kind": "log",
                        "mimeType": "text/plain",
                    }
                ],
            },
            required=True,
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_SCRIPT_ASSET_REQUIRED"
    else:
        raise AssertionError("Expected TOOL_RULE_SCRIPT_ASSET_REQUIRED")


def test_rule_template_rejects_script_action_conflicts() -> None:
    try:
        normalize_rule_template(
            {
                "script": "scripts/count_reads.py",
                "scriptAssets": [
                    {"path": "scripts/count_reads.py", "content": "print('ok')\n"}
                ],
                "wrapper": "v9.8.0/bio/demoqc",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "report",
                        "path": "report.txt",
                        "kind": "log",
                        "mimeType": "text/plain",
                    }
                ],
            },
            required=True,
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_ACTION_CONFLICT"
    else:
        raise AssertionError("Expected TOOL_RULE_ACTION_CONFLICT")


def test_generated_workflow_renders_snakemake_script_rule(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upsert_tool(
        cfg,
        {
            "id": "bioconda::script-rule",
            "name": "script-rule",
            "source": "bioconda",
            "packageSpec": "bioconda::python=3.12",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "script": "scripts/count_reads.py",
                "scriptAssets": [
                    {
                        "path": "scripts/count_reads.py",
                        "content": "from pathlib import Path\nPath(snakemake.output.report).write_text('ok\\n')\n",
                    }
                ],
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [
                    {
                        "name": "report",
                        "path": "script-report.txt",
                        "kind": "log",
                        "mimeType": "text/plain",
                    }
                ],
                "environment": {
                    "conda": {
                        "channels": ["conda-forge"],
                        "dependencies": ["python=3.12"],
                    }
                },
            },
        },
    )

    prepare_generated_tool_workflow(
        cfg,
        run_id="run_script_rule",
        request_id="req_script_rule",
        run_spec=generated_workflow_run_spec(
            "bioconda::script-rule", input_name="reads"
        ),
        resolved_inputs=_input(tmp_path),
        work_dir=tmp_path / "work",
        result_dir=tmp_path / "results",
    )

    snakefile = (tmp_path / "work" / "workflow" / "Snakefile").read_text(
        encoding="utf-8"
    )
    script = (tmp_path / "work" / "workflow" / "scripts" / "count_reads.py").read_text(
        encoding="utf-8"
    )
    run_config = json.loads(
        (tmp_path / "work" / "run-config.json").read_text(encoding="utf-8")
    )
    assert "script:" in snakefile
    assert "'scripts/count_reads.py'" in snakefile
    assert "conda:" in snakefile
    assert "shell:" not in snakefile
    assert "wrapper:" not in snakefile
    assert "snakemake.output.report" in script
    assert run_config["tool"]["ruleTemplate"]["script"] == "scripts/count_reads.py"


def test_generated_workflow_rejects_conflicting_script_asset_paths(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    for tool_id, content in [
        (
            "bioconda::script-a",
            "from pathlib import Path\nPath(snakemake.output.report).write_text('a\\n')\n",
        ),
        (
            "bioconda::script-b",
            "from pathlib import Path\nPath(snakemake.output.report).write_text('b\\n')\n",
        ),
    ]:
        upsert_tool(
            cfg,
            {
                "id": tool_id,
                "name": tool_id.rsplit("::", 1)[-1],
                "source": "bioconda",
                "packageSpec": "bioconda::python=3.12",
                "targetPlatformSupported": True,
                "ruleTemplate": {
                    "script": "scripts/run.py",
                    "scriptAssets": [{"path": "scripts/run.py", "content": content}],
                    "inputs": [
                        {
                            "name": "reads",
                            "type": "file",
                            "kind": "text",
                            "mimeType": "text/plain",
                            "required": True,
                        }
                    ],
                    "outputs": [
                        {
                            "name": "report",
                            "path": "report.txt",
                            "kind": "text",
                            "mimeType": "text/plain",
                        }
                    ],
                },
            },
        )

    try:
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_conflicting_script_assets",
            request_id="req_conflicting_script_assets",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        generated_workflow_node(
                            "bioconda::script-a",
                            node_id="first",
                            inputs={"reads": {"fromInput": "input"}},
                        ),
                        generated_workflow_node("bioconda::script-b", node_id="second"),
                    ],
                    "edges": [
                        {
                            "from": {"nodeId": "first", "port": "report"},
                            "to": {"nodeId": "second", "port": "reads"},
                        }
                    ],
                },
            },
            resolved_inputs=_input(tmp_path),
            work_dir=tmp_path / "work",
            result_dir=tmp_path / "results",
        )
    except ValueError as exc:
        assert str(exc) == "TOOL_RULE_SCRIPT_ASSET_CONFLICT: scripts/run.py"
    else:
        raise AssertionError("Expected conflicting script assets to fail loudly")
    assert not (tmp_path / "work").exists()


@pytest.mark.parametrize(
    ("tool_id", "script_path"),
    [
        ("bioconda::snakefile-collision", "Snakefile"),
        (
            "bioconda::env-collision",
            "envs/bioconda_env-collision.yaml",
        ),
    ],
)
def test_generated_workflow_reserves_generator_owned_paths_before_materialization(
    tmp_path: Path,
    tool_id: str,
    script_path: str,
) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _upsert_script_tool(cfg, tool_id=tool_id, script_path=script_path)
    work_dir = tmp_path / "work"

    with pytest.raises(
        ValueError,
        match="^TOOL_RULE_SCRIPT_ASSET_PATH_INVALID$",
    ):
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_reserved_asset_path",
            request_id="req_reserved_asset_path",
            run_spec=generated_workflow_run_spec(tool_id, input_name="reads"),
            resolved_inputs=_input(tmp_path),
            work_dir=work_dir,
            result_dir=tmp_path / "results",
        )

    assert not work_dir.exists()


def test_generated_workflow_rejects_cross_step_portable_alias_before_materialization(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    content = (
        "from pathlib import Path\nPath(snakemake.output.report).write_text('ok\\n')\n"
    )
    _upsert_script_tool(
        cfg,
        tool_id="bioconda::case-script-a",
        script_path="Scripts/run.py",
        content=content,
    )
    _upsert_script_tool(
        cfg,
        tool_id="bioconda::case-script-b",
        script_path="scripts/RUN.py",
        content=content,
    )
    work_dir = tmp_path / "work"

    with pytest.raises(
        ValueError,
        match="^TOOL_RULE_SCRIPT_ASSET_PATH_INVALID$",
    ):
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_cross_step_asset_alias",
            request_id="req_cross_step_asset_alias",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        generated_workflow_node(
                            "bioconda::case-script-a",
                            node_id="first",
                            inputs={"reads": {"fromInput": "input"}},
                        ),
                        generated_workflow_node(
                            "bioconda::case-script-b",
                            node_id="second",
                        ),
                    ],
                    "edges": [
                        {
                            "from": {"nodeId": "first", "port": "report"},
                            "to": {"nodeId": "second", "port": "reads"},
                        }
                    ],
                },
            },
            resolved_inputs=_input(tmp_path),
            work_dir=work_dir,
            result_dir=tmp_path / "results",
        )

    assert not work_dir.exists()
