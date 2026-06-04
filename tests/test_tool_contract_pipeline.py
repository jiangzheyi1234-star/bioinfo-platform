from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.pipeline import get_pipeline
from apps.remote_runner.preflight import RunPreflightError, preflight_run_spec
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.tool_contract_snakemake import run_snakemake
from apps.remote_runner.tool_contract_validation import _validate_outputs, run_tool_contract_validation
from apps.remote_runner.tools import (
    add_registered_tool,
    update_registered_tool_rule_template,
)
from tests.helpers.tool_contract_pipeline import (
    _cfg,
    _rule_contract_fields,
    _rule_resources,
    _runtime_commands,
    _validate_registered_tool,
)


def test_run_snakemake_does_not_mask_unexpected_subprocess_errors(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    snakefile = tmp_path / "Snakefile"
    config_path = tmp_path / "config.json"
    work_dir = tmp_path / "work"
    snakefile.write_text("rule all:\n    shell: 'true'\n", encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")

    def fake_run(*_args, **_kwargs):
        raise RuntimeError("runner adapter crashed")

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="runner adapter crashed"):
        run_snakemake(
            cfg,
            snakefile=snakefile,
            work_dir=work_dir,
            config_path=config_path,
            dry_run=True,
            timeout=30,
        )


def test_tool_contract_validation_does_not_mask_unexpected_prepare_errors(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    monkeypatch.setattr(
        "apps.remote_runner.tool_contract_validation.inspect_workflow_runtime",
        lambda _cfg: {"ok": True, "provider": "snakemake", "version": "9.0.0"},
    )

    def fail_materialize(*_args, **_kwargs):
        raise RuntimeError("workflow preparation adapter crashed")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation._materialize_smoke_inputs", fail_materialize)

    with pytest.raises(RuntimeError, match="workflow preparation adapter crashed"):
        run_tool_contract_validation(
            cfg,
            {
                "id": "conda-forge::prepare-crash",
                "name": "prepare-crash",
                "ruleTemplate": {
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                },
            },
        )


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
    assert saved["toolContract"]["state"] == "AddedDependency"
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
    assert contract["state"] == "AddedDependency"
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

    assert saved["toolContract"]["state"] == "AddedDependency"
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
    assert contract["state"] == "AddedDependency"
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

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

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

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

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

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

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
    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)
    checked = _validate_registered_tool(cfg, "conda-forge::coreutils-db")
    assert checked["contractStatus"]["dryRun"]["status"] == "passed"
    assert checked["contractStatus"]["smokeRun"]["status"] == "passed"
    assert checked["contractStatus"]["outputValidation"]["status"] == "passed"
    assert checked["toolContract"]["state"] == "WorkflowReady"
    assert checked["toolContract"]["workflowReady"] is True
