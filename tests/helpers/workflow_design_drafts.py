from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig
from tests.generated_workflow_test_helpers import test_tool_revision_id
from tests.helpers.reference_database import make_configured_remote_runner


def workflow_design_config(tmp_path: Path) -> RemoteRunnerConfig:
    return make_configured_remote_runner(tmp_path, token="workflow-design-token")


def workflow_design_tool_manifest(tool_id: str = "bioconda::qc=1.0") -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": "qc",
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": tool_id,
        "summary": "QC fixture",
        "ruleTemplate": {
            "inputs": [{"name": "reads", "required": True, "kind": "reads", "format": "fastq"}],
            "outputs": [
                {
                    "name": "report",
                    "path": "qc-report.txt",
                    "kind": "report",
                    "mimeType": "text/plain",
                }
            ],
            "params": {"min_len": {"type": "integer", "default": 50}},
            "commandTemplate": "printf 'qc {params.min_len}' > {output.report:q}",
        },
    }


def workflow_design_draft(tool_id: str = "bioconda::qc=1.0") -> dict[str, Any]:
    return {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {
            "name": "QC workflow",
            "description": "Saved workflow design fixture",
            "projectId": "proj_design",
            "tags": ["qc"],
        },
        "inputs": [
            {
                "id": "reads",
                "role": "input",
                "path": "inputs/reads.fastq",
                "mimeType": "text/plain",
                "metadata": {"lane": "L001"},
            }
        ],
        "nodes": [
            {
                "id": "qc",
                "toolRevisionId": test_tool_revision_id(tool_id),
                "inputs": {"reads": {"fromInput": "input"}},
                "params": {"min_len": 80},
                "runtime": {"threads": 2, "schedulerResources": {"mem_mb": 256}},
                "resources": {},
                "outputs": {"report": {"expose": True, "metadata": {"panel": "summary"}}},
                "metadata": {"uiGroup": "qc"},
                "provenance": {"source": "builder"},
            }
        ],
        "edges": [],
        "resources": {"bindings": {}, "metadata": {"selectionMode": "manual"}},
        "outputs": [
            {
                "from": {"nodeId": "qc", "port": "report"},
                "as": "qc_report",
                "metadata": {"audience": "operator"},
            }
        ],
        "provenance": {"createdBy": "test"},
    }
