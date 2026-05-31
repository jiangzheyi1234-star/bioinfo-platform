from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.storage import create_run_record, persist_artifact, update_run_state, upsert_tool
from apps.remote_runner.tools import ToolRegistryError, add_registered_tool, mark_registered_tool_production_enabled
from tests.generated_workflow_test_helpers import generated_workflow_node, generated_workflow_run_spec


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="tool-production-evidence-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def _ready_tool(cfg: RemoteRunnerConfig) -> None:
    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::production-ready",
            "name": "production-ready",
            "source": "conda-forge",
            "packageSpec": "conda-forge::production-ready=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/production-ready.log",
                "environment": {
                    "conda": {"channels": ["conda-forge", "bioconda"], "dependencies": ["conda-forge::production-ready=9.5"]}
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )
    saved["contractStatus"]["dryRun"] = {"status": "passed", "message": "Snakemake dry-run passed."}
    saved["contractStatus"]["smokeRun"] = {"status": "passed", "message": "Snakemake smoke run passed."}
    saved["contractStatus"]["outputValidation"] = {"status": "passed", "message": "Output validation passed."}
    upsert_tool(cfg, saved)


def _completed_run_with_artifact(
    cfg: RemoteRunnerConfig,
    tmp_path: Path,
    run_id: str = "run_real_data",
    run_spec: dict[str, object] | None = None,
    artifact_content: str = "accepted\n",
) -> None:
    result_dir = tmp_path / "results" / run_id
    result_dir.mkdir(parents=True, exist_ok=True)
    artifact = result_dir / "report.txt"
    artifact.write_text(artifact_content, encoding="utf-8")
    stored_run_spec = dict(run_spec or generated_workflow_run_spec("conda-forge::production-ready"))
    stored_run_spec["runId"] = run_id
    create_run_record(
        cfg,
        server_id="srv_production",
        request_id=f"req_{run_id}",
        run_spec=stored_run_spec,
        idempotency_key=f"idem_{run_id}",
        payload_hash=f"hash_{run_id}",
    )
    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="completed",
        message="completed",
        request_id=f"req_{run_id}",
        result_dir=str(result_dir),
    )
    persist_artifact(cfg, run_id=run_id, kind="report", path=artifact, mime_type="text/plain")


def _production_run_spec(*, resource_bindings: dict[str, object] | None = None) -> dict[str, object]:
    return generated_workflow_run_spec("conda-forge::production-ready", resource_bindings=resource_bindings)


def _registered_database(cfg: RemoteRunnerConfig, tmp_path: Path, *, template_id: str, status: str = "available") -> None:
    database_dir = tmp_path / f"db-{template_id}-{status}"
    database_dir.mkdir(parents=True, exist_ok=True)
    add_reference_database(
        cfg,
        {
            "id": "db_real",
            "name": "Real DB",
            "templateId": template_id,
            "path": str(database_dir),
            "status": status,
            "metadata": {"templateId": template_id},
        },
    )


def test_production_acceptance_requires_workflow_ready_contract(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::output-only",
            "name": "output-only",
            "source": "conda-forge",
            "packageSpec": "conda-forge::output-only=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/output-only.log",
                "environment": {
                    "conda": {"channels": ["conda-forge", "bioconda"], "dependencies": ["conda-forge::output-only=9.5"]}
                },
            },
        },
    )
    saved["contractStatus"]["dryRun"] = {"status": "passed"}
    saved["contractStatus"]["smokeRun"] = {"status": "passed"}
    saved["contractStatus"]["outputValidation"] = {"status": "passed"}
    upsert_tool(cfg, saved)
    _completed_run_with_artifact(cfg, tmp_path)

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::output-only",
            {"runId": "run_real_data", "message": "Accepted against real remote data."},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY"
    else:
        raise AssertionError("Production evidence should require a WorkflowReady contract.")


def test_production_acceptance_requires_real_evidence_payload(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)

    for evidence, expected in [
        ({}, "TOOL_PRODUCTION_EVIDENCE_RUN_ID_REQUIRED"),
        ({"runId": "run_real_data"}, "TOOL_PRODUCTION_EVIDENCE_MESSAGE_REQUIRED"),
        (
            {"runId": "run_real_data", "message": "Accepted against real remote data."},
            "TOOL_PRODUCTION_EVIDENCE_TYPE_REQUIRED",
        ),
    ]:
        try:
            mark_registered_tool_production_enabled(cfg, "conda-forge::production-ready", evidence)
        except ToolRegistryError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"Production evidence should require {expected}")

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_missing", "message": "Accepted against real remote data.", "evidenceType": "real-data-acceptance"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND"
    else:
        raise AssertionError("Production evidence should reference a stored remote run")

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_real_data", "message": "Accepted.", "evidenceType": "manual-note"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_TYPE_INVALID"
    else:
        raise AssertionError("Production evidence type should be a real remote acceptance contract.")

    _completed_run_with_artifact(cfg, tmp_path)

    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::production-ready",
        {
            "runId": "run_real_data",
            "message": "Accepted against real remote data.",
            "evidenceType": "real-data-acceptance",
            "databaseId": "db_real",
            "templateId": "custom",
        },
    )

    production = accepted["contractStatus"]["production"]
    assert production["status"] == "passed"
    assert production["runId"] == "run_real_data"
    assert production["evidenceType"] == "real-data-acceptance"
    assert production["databaseId"] == "db_real"
    assert production["templateId"] == "custom"
    assert production["artifactCount"] == "1"
    assert production["artifactNames"] == "report.txt"
    assert accepted["toolContract"]["state"] == "ProductionEnabled"


def test_production_acceptance_evidence_must_match_generated_tool_run(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)

    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_wrong_pipeline",
        run_spec={"runId": "run_wrong_pipeline", "pipelineId": "file-summary-v1"},
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_wrong_pipeline", "message": "Accepted.", "evidenceType": "real-data-acceptance"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_PIPELINE_MISMATCH"
    else:
        raise AssertionError("Production evidence should come from generated-tool-run-v1.")

    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_wrong_tool",
        run_spec=generated_workflow_run_spec("conda-forge::other-tool"),
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_wrong_tool", "message": "Accepted.", "evidenceType": "real-data-acceptance"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_TOOL_MISMATCH"
    else:
        raise AssertionError("Production evidence should match the accepted tool id.")


def test_real_database_production_evidence_must_match_run_binding(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)
    _completed_run_with_artifact(cfg, tmp_path, run_id="run_database_missing_binding")

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_database_missing_binding", "message": "Accepted.", "evidenceType": "real-database-acceptance"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_DATABASE_REQUIRED"
    else:
        raise AssertionError("Real database acceptance should require database evidence fields.")

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {
                "runId": "run_database_missing_binding",
                "message": "Accepted.",
                "evidenceType": "real-database-acceptance",
                "databaseId": "db_real",
                "templateId": "custom",
                "role": "taxonomy",
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH"
    else:
        raise AssertionError("Real database acceptance should match run resourceBindings.")

    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_database_wrong_template",
        run_spec=_production_run_spec(resource_bindings={"taxonomy": {"databaseId": "db_real", "templateId": "kraken2"}}),
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {
                "runId": "run_database_wrong_template",
                "message": "Accepted.",
                "evidenceType": "real-database-acceptance",
                "databaseId": "db_real",
                "templateId": "custom",
                "role": "taxonomy",
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH"
    else:
        raise AssertionError("Real database acceptance should match the run resource binding template.")

    _registered_database(cfg, tmp_path, template_id="kraken2")
    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_database_self_reported_template",
        run_spec=_production_run_spec(resource_bindings={"taxonomy": {"databaseId": "db_real", "templateId": "custom"}}),
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {
                "runId": "run_database_self_reported_template",
                "message": "Accepted.",
                "evidenceType": "real-database-acceptance",
                "databaseId": "db_real",
                "templateId": "custom",
                "role": "taxonomy",
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH"
    else:
        raise AssertionError("Real database acceptance should match the registered database template.")

    _registered_database(cfg, tmp_path, template_id="custom", status="failed")
    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_database_unavailable",
        run_spec=_production_run_spec(resource_bindings={"taxonomy": {"databaseId": "db_real", "templateId": "custom"}}),
    )
    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {
                "runId": "run_database_unavailable",
                "message": "Accepted.",
                "evidenceType": "real-database-acceptance",
                "databaseId": "db_real",
                "templateId": "custom",
                "role": "taxonomy",
            },
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_DATABASE_UNAVAILABLE"
    else:
        raise AssertionError("Real database acceptance should require an available database registry record.")

    _registered_database(cfg, tmp_path, template_id="custom")
    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_database_matched",
        run_spec=_production_run_spec(resource_bindings={"taxonomy": {"databaseId": "db_real", "templateId": "custom"}}),
    )
    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::production-ready",
        {
            "runId": "run_database_matched",
            "message": "Accepted.",
            "evidenceType": "real-database-acceptance",
            "databaseId": "db_real",
            "templateId": "custom",
            "role": "taxonomy",
        },
    )

    assert accepted["toolContract"]["state"] == "ProductionEnabled"


def test_production_acceptance_rejects_empty_artifacts(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)
    _completed_run_with_artifact(cfg, tmp_path, run_id="run_empty_artifact", artifact_content="")

    try:
        mark_registered_tool_production_enabled(
            cfg,
            "conda-forge::production-ready",
            {"runId": "run_empty_artifact", "message": "Accepted.", "evidenceType": "real-data-acceptance"},
        )
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_PRODUCTION_EVIDENCE_ARTIFACT_EMPTY"
    else:
        raise AssertionError("Production evidence should reject empty generated artifacts.")


def test_production_acceptance_evidence_accepts_graph_workflow_nodes(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _ready_tool(cfg)
    _completed_run_with_artifact(
        cfg,
        tmp_path,
        run_id="run_graph_tool",
        run_spec={
            "runId": "run_graph_tool",
            "pipelineId": "generated-tool-run-v1",
            "workflow": {
                "contractVersion": "rule-contract-v1",
                "nodes": [generated_workflow_node("conda-forge::production-ready", node_id="copy_report")],
                "edges": [],
                "outputs": [],
            },
        },
    )

    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::production-ready",
        {"runId": "run_graph_tool", "message": "Accepted.", "evidenceType": "real-data-acceptance"},
    )

    assert accepted["toolContract"]["state"] == "ProductionEnabled"
