from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from apps.remote_runner.pipeline import get_pipeline
from apps.remote_runner.preflight import RunPreflightError, preflight_run_spec
from apps.remote_runner.storage import create_run_record, fetch_tool, now_iso, persist_artifact, update_run_state, upsert_tool
from apps.remote_runner.tool_contract import build_tool_contract, default_contract_status
from apps.remote_runner.tool_contract_validation import _validate_outputs, run_tool_contract_validation
from apps.remote_runner.tools import (
    ToolRegistryError,
    add_registered_tool,
    mark_registered_tool_production_enabled,
    normalize_rule_template,
    update_registered_tool_rule_template,
)


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    workflow_bin = tmp_path / "workflow-env" / "bin"
    return RemoteRunnerConfig(
        token="tool-contract-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(workflow_bin / "conda"),
        snakemake_command=str(workflow_bin / "snakemake"),
    )


def _runtime_commands(tmp_path: Path) -> None:
    workflow_bin = tmp_path / "workflow-env" / "bin"
    workflow_bin.mkdir(parents=True, exist_ok=True)
    for command in ["conda", "snakemake"]:
        path = workflow_bin / command
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)


def _reads(tmp_path: Path) -> list[dict[str, str]]:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@r1\nACGT\n+\nFFFF\n", encoding="utf-8")
    return [{"path": str(reads), "role": "input", "filename": "reads.fastq"}]


def _rule_resources() -> dict[str, dict[str, int]]:
    return {"threads": {"default": 1}, "mem_mb": {"default": 128}}


def _rule_contract_fields() -> dict[str, object]:
    return {"params": {}, "resources": _rule_resources(), "log": "logs/tool.log"}


def _validate_registered_tool(cfg: RemoteRunnerConfig, tool_id: str) -> dict[str, Any]:
    item = fetch_tool(cfg, tool_id)
    if item is None:
        raise AssertionError(f"missing tool fixture: {tool_id}")
    try:
        item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=True)
    except ToolRegistryError as exc:
        item["contractStatus"] = _contract_failure_status("dryRun", str(exc), str(exc))
        item["status"] = "failed"
        item["message"] = str(exc)
        return upsert_tool(cfg, item)
    contract = build_tool_contract(item)
    if not bool(contract["requirements"]["snakemakeRenderable"]):
        code = str((contract.get("reasons") or ["TOOL_CONTRACT_INCOMPLETE"])[0])
        item["contractStatus"] = _contract_failure_status("dryRun", code, code)
        item["status"] = "failed"
        item["message"] = code
        return upsert_tool(cfg, item)
    result = run_tool_contract_validation(cfg, item)
    item["contractStatus"] = result["contractStatus"]
    item["status"] = "declared" if result["ok"] else "failed"
    item["message"] = str(result["message"] or "")
    return upsert_tool(cfg, item)


def _contract_failure_status(key: str, code: str, message: str) -> dict[str, dict[str, str]]:
    status = default_contract_status()
    status[key] = {"status": "failed", "code": code, "message": message, "checkedAt": now_iso()}
    return status


def test_added_dependency_contract_is_not_workflow_ready(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
        },
    )

    assert saved["toolContract"]["state"] == "AddedDependency"
    assert saved["toolContract"]["workflowReady"] is False
    assert saved["toolContract"]["package"]["packageSpec"] == "conda-forge::coreutils=9.5"
    assert saved["contractStatus"]["dryRun"]["status"] == "not_run"


def test_rulespec_update_promotes_contract_to_snakemake_renderable(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::demoqc",
            "name": "demoqc",
            "source": "bioconda",
            "packageSpec": "bioconda::demoqc=0.12.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "conda-package",
                "requiresUserCompletion": True,
                "ruleTemplate": {"commandTemplate": "demoqc {input.reads:q} --outdir {output.qc_dir:q}"},
            },
        },
    )
    assert saved["toolContract"]["state"] == "RuleSpecDrafted"
    assert saved["toolContract"]["workflowReady"] is False

    saved = update_registered_tool_rule_template(
        cfg,
        "bioconda::demoqc",
        {
            "commandTemplate": "mkdir -p {output.qc_dir:q} && demoqc {input.reads:q} --outdir {output.qc_dir:q}",
            "inputs": [{"name": "reads", "type": "file", "kind": "sequence", "required": True}],
            "outputs": [
                {
                    "name": "qc_dir",
                    "path": "results/demoqc",
                    "kind": "report",
                    "mimeType": "inode/directory",
                    "directory": True,
                }
            ],
            **_rule_contract_fields(),
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["bioconda::demoqc=0.12.1"],
                }
            },
        },
    )

    contract = saved["toolContract"]
    assert contract["state"] == "SnakemakeRenderable"
    assert contract["workflowReady"] is False
    assert contract["requirements"]["ruleSpecConfirmed"] is True
    assert contract["requirements"]["environmentSpecified"] is True
    assert contract["validation"]["dryRun"]["status"] == "not_run"

    try:
        preflight_run_spec(
            cfg,
            get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID),
            {"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "bioconda::demoqc"}},
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated-tool runs must come from a saved WorkflowDesignDraft")


def test_rulespec_requires_params_runtime_resources_and_log(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::runtime-missing",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
            },
        },
    )

    contract = saved["toolContract"]
    assert contract["state"] == "RuleSpecDrafted"
    assert contract["workflowReady"] is False
    assert contract["requirements"]["ruleSpecConfirmed"] is False
    assert "TOOL_RULE_THREADS_REQUIRED" in contract["reasons"]
    assert "TOOL_RULE_RESOURCES_REQUIRED" in contract["reasons"]
    assert "TOOL_RULE_LOG_REQUIRED" in contract["reasons"]


def test_rulespec_requires_explicit_params_schema(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::params-missing",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "resources": _rule_resources(),
                "log": "logs/tool.log",
                "environment": {"conda": {"channels": ["conda-forge"], "dependencies": ["conda-forge::coreutils=9.5"]}},
            },
        },
    )

    assert saved["toolContract"]["state"] == "RuleSpecDrafted"
    assert saved["toolContract"]["requirements"]["ruleSpecConfirmed"] is False
    assert "TOOL_RULE_PARAMS_REQUIRED" in saved["toolContract"]["reasons"]


def test_dry_run_passed_contract_is_not_workflow_ready(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::dry-run-only",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )
    saved["contractStatus"]["dryRun"] = {"status": "passed", "message": "dry-run only"}
    saved = upsert_tool(cfg, saved)

    assert saved["toolContract"]["state"] == "DryRunPassed"
    assert saved["toolContract"]["workflowReady"] is False
    try:
        preflight_run_spec(
            cfg,
            get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID),
            {"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "conda-forge::dry-run-only"}},
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated-tool runs must come from a saved WorkflowDesignDraft")


def test_rulespec_without_explicit_environment_is_not_renderable(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
            },
        },
    )

    assert saved["toolContract"]["state"] == "RuleSpecConfirmed"
    assert saved["toolContract"]["requirements"]["environmentSpecified"] is False

    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")

    assert checked["contractStatus"]["dryRun"]["status"] == "failed"
    assert checked["contractStatus"]["dryRun"]["code"] == "TOOL_RULE_ENVIRONMENT_REQUIRED"
    assert checked["lastCheckedAt"] == checked["contractStatus"]["dryRun"]["checkedAt"]
    assert checked["toolContract"]["workflowReady"] is False


def test_environment_requires_locked_dependencies_and_bioconda_channel_priority(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "conda-forge::unlocked-env",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["bioconda", "conda-forge"],
                        "dependencies": ["coreutils"],
                    }
                },
            },
        },
    )

    contract = saved["toolContract"]
    assert contract["state"] == "RuleSpecConfirmed"
    assert contract["requirements"]["environmentSpecified"] is False
    assert contract["environment"]["locked"] is False
    assert contract["environment"]["channelPriorityStrict"] is False
    assert "TOOL_RULE_ENVIRONMENT_LOCK_REQUIRED" in contract["reasons"]
    assert "TOOL_RULE_ENVIRONMENT_CHANNEL_PRIORITY_REQUIRED" in contract["reasons"]


def test_wrapper_rulespec_requires_locked_wrapper_ref(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::unlocked-demoqc-wrapper",
            "name": "demoqc",
            "source": "bioconda",
            "packageSpec": "bioconda::demoqc=0.12.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "wrapper": "bio/demoqc",
                "inputs": [{"name": "reads", "type": "file", "required": True}],
                "outputs": [{"name": "html", "path": "demoqc.html", "kind": "html", "mimeType": "text/html"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["bioconda::demoqc=0.12.1"],
                    }
                },
            },
        },
    )

    contract = saved["toolContract"]
    assert contract["state"] == "RuleSpecDrafted"
    assert contract["requirements"]["ruleSpecConfirmed"] is False
    assert contract["ruleSpec"]["wrapperLocked"] is False
    assert "TOOL_RULE_WRAPPER_LOCK_REQUIRED" in contract["reasons"]

    checked = _validate_registered_tool(cfg, "bioconda::unlocked-demoqc-wrapper")
    assert checked["contractStatus"]["dryRun"]["status"] == "failed"
    assert checked["contractStatus"]["dryRun"]["code"] == "TOOL_RULE_WRAPPER_LOCK_REQUIRED"


def test_rulespec_update_resets_previous_contract_validation(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
            },
        },
    )

    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")
    assert checked["lastCheckedAt"]

    saved = update_registered_tool_rule_template(
        cfg,
        "conda-forge::coreutils",
        {
            "commandTemplate": "cp {input.primary:q} {output.report:q}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
            **_rule_contract_fields(),
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["conda-forge::coreutils=9.5"],
                }
            },
        },
    )

    assert saved["lastCheckedAt"] is None
    assert saved["contractStatus"]["dryRun"]["status"] == "not_run"


def test_tool_validation_promotes_contract_through_dry_run_smoke_and_output_validation(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {
                    "inputs": {
                        "primary": {
                            "filename": "input.txt",
                            "content": "hello\n",
                            "mimeType": "text/plain",
                        }
                    }
                },
            },
        },
    )
    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        if "-n" not in cmd:
            config_path = Path(cmd[cmd.index("--configfile") + 1])
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            Path(run_config["outputs"]["report"]).parent.mkdir(parents=True, exist_ok=True)
            Path(run_config["outputs"]["report"]).write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)

    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")

    assert checked["contractStatus"]["dryRun"]["status"] == "passed"
    assert checked["contractStatus"]["smokeRun"]["status"] == "passed"
    assert checked["contractStatus"]["outputValidation"]["status"] == "passed"
    assert checked["lastCheckedAt"] == checked["contractStatus"]["outputValidation"]["checkedAt"]
    dry_run_log = Path(checked["contractStatus"]["dryRun"]["logPath"])
    smoke_run_log = Path(checked["contractStatus"]["smokeRun"]["logPath"])
    assert dry_run_log.read_text(encoding="utf-8")
    assert smoke_run_log.read_text(encoding="utf-8")
    assert checked["toolContract"]["state"] == "WorkflowReady"
    assert checked["toolContract"]["workflowReady"] is True


def test_tool_validation_records_stable_dry_run_failure(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
            },
        },
    )

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        if "-n" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing rule input\n")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)

    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")

    assert checked["contractStatus"]["dryRun"]["status"] == "failed"
    assert checked["contractStatus"]["dryRun"]["code"] == "SNAKEMAKE_DRY_RUN_FAILED"
    assert checked["contractStatus"]["smokeRun"]["status"] == "not_run"
    assert checked["toolContract"]["state"] == "SnakemakeRenderable"
    assert checked["toolContract"]["workflowReady"] is False


def test_tool_validation_records_stable_output_validation_failure(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "true",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )

    def fake_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)

    checked = _validate_registered_tool(cfg, "conda-forge::coreutils")

    assert checked["contractStatus"]["dryRun"]["status"] == "passed"
    assert checked["contractStatus"]["smokeRun"]["status"] == "passed"
    assert checked["contractStatus"]["outputValidation"]["status"] == "failed"
    assert checked["contractStatus"]["outputValidation"]["code"] == "OUTPUT_ARTIFACT_MISSING"
    assert checked["toolContract"]["state"] == "SmokeRunPassed"
    assert checked["toolContract"]["workflowReady"] is False
    try:
        preflight_run_spec(
            cfg,
            get_pipeline(cfg, GENERATED_TOOL_RUN_PIPELINE_ID),
            {"pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "tool": {"id": "conda-forge::coreutils"}},
        )
    except RunPreflightError as exc:
        assert str(exc) == "WORKFLOW_DESIGN_RUN_SPEC_REQUIRED"
    else:
        raise AssertionError("direct generated-tool runs must come from a saved WorkflowDesignDraft")


def test_output_validation_rejects_blank_text_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "report.txt"
    output.write_text(" \n\t\n", encoding="utf-8")

    error = _validate_outputs(
        output_schema={
            "artifacts": [
                {"key": "report", "mimeType": "text/plain", "name": "report.txt"},
            ]
        },
        outputs={"report": str(output)},
    )

    assert error == {"code": "OUTPUT_ARTIFACT_EMPTY", "message": "Output file is blank: report"}


def test_tool_validation_uses_smoke_resource_bindings_for_database_rules(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    database_dir = tmp_path / "custom-db"
    database_dir.mkdir()
    (database_dir / "manifest.txt").write_text("custom\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_custom",
            "name": "Custom DB",
            "templateId": "custom",
            "type": "taxonomy",
            "path": str(database_dir),
            "status": "available",
            "metadata": {"templateId": "custom"},
        },
    )
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::coreutils-db",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\n' {config.taxonomy:q} > {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "database-path.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "resources": {**_rule_resources(), "taxonomy": {"type": "database", "configKey": "taxonomy"}},
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {
                    "inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}},
                    "resourceBindings": {"taxonomy": {"databaseId": "db_custom"}},
                },
            },
        },
    )

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        if "-n" not in cmd:
            config_path = Path(cmd[cmd.index("--configfile") + 1])
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            assert run_config["resourceConfig"]["taxonomy"] == str(database_dir)
            Path(run_config["outputs"]["report"]).parent.mkdir(parents=True, exist_ok=True)
            Path(run_config["outputs"]["report"]).write_text(str(database_dir), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)
    checked = _validate_registered_tool(cfg, "conda-forge::coreutils-db")
    assert checked["contractStatus"]["dryRun"]["status"] == "passed"
    assert checked["contractStatus"]["smokeRun"]["status"] == "passed"
    assert checked["contractStatus"]["outputValidation"]["status"] == "passed"
    assert checked["toolContract"]["state"] == "WorkflowReady"
    assert checked["toolContract"]["workflowReady"] is True

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
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(), "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
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
    upsert_tool(cfg, checked)
    result_dir = tmp_path / "production-result"
    result_dir.mkdir()
    artifact = result_dir / "report.txt"
    artifact.write_text("accepted\n", encoding="utf-8")
    create_run_record(cfg, server_id="srv", request_id="req", run_spec={"runId": "run_real_data", "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID, "workflow": {"contractVersion": "rule-contract-v1", "nodes": [{"id": "run_tool", "tool": {"id": "conda-forge::coreutils"}}], "edges": []}}, idempotency_key="idem", payload_hash="hash")
    update_run_state(cfg, run_id="run_real_data", status="completed", stage="completed", message="completed", request_id="req", result_dir=str(result_dir))
    persist_artifact(cfg, run_id="run_real_data", kind="report", path=artifact, mime_type="text/plain")

    accepted = mark_registered_tool_production_enabled(
        cfg,
        "conda-forge::coreutils",
        {
            "runId": "run_real_data",
            "message": "Accepted against real remote data.",
            "logPath": "/remote/logs/run_real_data.log", "evidenceType": "real-data-acceptance",
        },
    )

    assert accepted["contractStatus"]["production"]["status"] == "passed"
    assert accepted["contractStatus"]["production"]["code"] == "PRODUCTION_ACCEPTED"
    assert accepted["contractStatus"]["production"]["runId"] == "run_real_data"
    assert accepted["contractStatus"]["production"]["logPath"] == "/remote/logs/run_real_data.log"
    assert accepted["toolContract"]["state"] == "ProductionEnabled"
    assert accepted["toolContract"]["requirements"]["productionEnabled"] is True

def test_generated_workflow_cannot_bypass_registered_contract_with_request_rulespec(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::request-only",
            "name": "coreutils",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
        },
    )
    try:
        prepare_generated_tool_workflow(
            cfg,
            run_id="run_request_only",
            request_id="req_request_only",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "workflow": {
                    "contractVersion": "rule-contract-v1",
                    "nodes": [
                        {
                            "id": "run_tool",
                            "tool": {
                                "id": "conda-forge::request-only",
                                "ruleTemplate": {
                                    "commandTemplate": "wc -c {input.reads:q} > {output.report:q}",
                                    "inputs": [{"name": "reads", "type": "file", "required": True}],
                                    "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                                },
                            },
                            "inputs": {"reads": {"fromInput": "input"}},
                        }
                    ],
                    "edges": [],
                },
            },
            resolved_inputs=_reads(tmp_path),
            work_dir=tmp_path / "work",
            result_dir=tmp_path / "results",
        )
    except ValueError as exc:
        assert str(exc) == "WORKFLOW_STEP_TOOL_UNSUPPORTED_FIELD: ruleTemplate"
    else:
        raise AssertionError("runSpec RuleSpec must not bypass the registered tool contract")

def test_tool_production_acceptance_is_exposed_through_api_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_main = (root / "apps" / "remote_runner" / "main.py").read_text(encoding="utf-8")
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_main = (root / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    local_route = (root / "apps" / "api" / "tool_contract_routes.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (root / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    assert "tool_router" in remote_main
    assert '@router.post("/api/v1/tools/{tool_id}/production")' in remote_route
    assert "mark_registered_tool_production_enabled" in remote_route
    assert "tool_contract_router" in local_main
    assert '@router.post("/api/v1/tools/{tool_id}/production")' in local_route
    assert 'await invalidate_response_cache("tools", "workflow_catalog")' in local_route
    assert "def mark_tool_production_enabled" in proxy
    assert "/api/v1/tools/{kwargs['tool_id']}/production" in proxy
    assert "def mark_tool_production_enabled" in runner_ops
