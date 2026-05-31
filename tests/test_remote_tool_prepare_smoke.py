from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import remote_tool_prepare_smoke


def test_fastqc_prepare_payload_uses_locked_command_template_contract() -> None:
    payload = remote_tool_prepare_smoke.build_fastqc_prepare_payload("bioconda::fastqc-prepare-smoke-test")
    rule = payload["ruleTemplate"]

    assert payload["id"] == "bioconda::fastqc-prepare-smoke-test"
    assert payload["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert payload["targetPlatform"] == "linux-64"
    assert payload["targetPlatformSupported"] is True
    assert "serverId" not in payload
    assert rule["commandTemplate"] == "mkdir -p {output.qc_dir:q} && fastqc {input.reads:q} --outdir {output.qc_dir:q}"
    assert rule["environment"]["conda"]["channels"] == ["conda-forge", "bioconda"]
    assert rule["environment"]["conda"]["dependencies"] == ["bioconda::fastqc=0.12.1"]
    assert rule["outputs"] == [
        {
            "name": "qc_dir",
            "path": "results/fastqc",
            "kind": "report",
            "mimeType": "application/vnd.h2ometa.directory",
            "directory": True,
        }
    ]
    assert rule["smokeTest"]["inputs"]["reads"]["content"].startswith("@smoke")


def test_prepare_summary_requires_workflow_ready_validation_phases() -> None:
    summary = remote_tool_prepare_smoke.summarize_prepared_tool(
        {
            "data": {
                "id": "bioconda::fastqc-prepare-smoke",
                "status": "declared",
                "message": "Tool contract validation passed.",
                "contractStatus": {
                    "dryRun": {"status": "passed", "logPath": "/tmp/dry.log"},
                    "smokeRun": {"status": "passed", "runId": "toolcheck_fastqc"},
                    "outputValidation": {"status": "passed", "artifactCount": "1"},
                    "production": {"status": "not_run"},
                },
                "toolContract": {
                    "state": "WorkflowReady",
                    "workflowReady": True,
                    "requirements": {"productionEnabled": False},
                },
            }
        }
    )

    assert remote_tool_prepare_smoke.prepared_tool_ready(summary) is True
    assert summary["state"] == "WorkflowReady"
    assert summary["productionEnabled"] is False
    assert summary["phases"]["production"] == "not_run"


def test_prepare_summary_rejects_missing_output_validation() -> None:
    summary = {
        "workflowReady": True,
        "state": "WorkflowReady",
        "phases": {"dryRun": "passed", "smokeRun": "passed", "outputValidation": "not_run"},
    }

    assert remote_tool_prepare_smoke.prepared_tool_ready(summary) is False
