from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import create_run_record, persist_artifact, update_run_state, upsert_tool
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool, mark_registered_tool_production_enabled
from tests.helpers.tool_contract_pipeline import _cfg, _rule_contract_fields, _validate_registered_tool


TOOL_REVISION_ID = "conda-forge::coreutils#production-acceptance"


def test_production_acceptance_requires_output_validation_and_records_evidence(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "toolRevisionId": TOOL_REVISION_ID,
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
            },
        },
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::coreutils",
            {"runId": "run_real_data", "message": "Accepted against real remote data."},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION"
    else:
        raise AssertionError("Production acceptance must require output validation first")
    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")
    checked["contractStatus"]["dryRun"] = {"status": "passed", "message": "Snakemake dry-run passed."}
    checked["contractStatus"]["smokeRun"] = {"status": "passed", "message": "Snakemake smoke run passed."}
    checked["contractStatus"]["outputValidation"] = {"status": "passed", "message": "Output validation passed."}
    checked["toolRevisionId"] = TOOL_REVISION_ID
    upsert_tool(cfg, checked)
    result_dir = tmp_path / "production-result"
    result_dir.mkdir()
    artifact = result_dir / "report.txt"
    artifact.write_text("accepted\n", encoding="utf-8")
    create_run_record(
        cfg,
        server_id="srv",
        request_id="req",
        run_spec={
            "runId": "run_real_data",
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": {
                "contractVersion": "rule-contract-v1",
                "nodes": [{"id": "run_tool", "toolRevisionId": TOOL_REVISION_ID}],
                "edges": [],
            },
        },
        idempotency_key="idem",
        payload_hash="hash",
    )
    update_run_state(
        cfg,
        run_id="run_real_data",
        status="completed",
        stage="completed",
        message="completed",
        request_id="req",
        result_dir=str(result_dir),
    )
    persist_artifact(cfg, run_id="run_real_data", kind="report", path=artifact, mime_type="text/plain")

    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::coreutils",
        {
            "runId": "run_real_data",
            "message": "Accepted against real remote data.",
            "logPath": "/remote/logs/run_real_data.log",
            "evidenceType": "real-data-acceptance",
        },
    )

    assert accepted["contractStatus"]["production"]["status"] == "passed"
    assert accepted["contractStatus"]["production"]["code"] == "PRODUCTION_ACCEPTED"
    assert accepted["contractStatus"]["production"]["runId"] == "run_real_data"
    assert accepted["contractStatus"]["production"]["logPath"] == "/remote/logs/run_real_data.log"
    assert accepted["toolContract"]["state"] == "ProductionEnabled"
    assert accepted["toolContract"]["requirements"]["productionEnabled"] is True
