from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database
from apps.remote_runner.tools import add_registered_tool
from tests.test_tool_contract_pipeline import _cfg, _rule_contract_fields, _runtime_commands, _validate_registered_tool


def test_tool_validation_requires_explicit_smoke_input_fixtures(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::no-smoke-fixture",
            "name": "no-smoke-fixture",
            "source": "conda-forge",
            "packageSpec": "conda-forge::no-smoke-fixture=9.5",
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
                        "dependencies": ["conda-forge::no-smoke-fixture=9.5"],
                    }
                },
            },
        },
    )
    snakemake_commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" not in cmd:
            snakemake_commands.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

    checked = _validate_registered_tool(cfg, "conda-forge::no-smoke-fixture")

    assert checked["contractStatus"]["dryRun"]["status"] == "passed"
    assert checked["contractStatus"]["smokeRun"]["status"] == "failed"
    assert checked["contractStatus"]["smokeRun"]["code"] == "TOOL_RULE_SMOKE_TEST_REQUIRED"
    assert checked["contractStatus"]["outputValidation"]["status"] == "not_run"
    assert checked["toolContract"]["state"] == "DryRunPassed"
    assert checked["toolContract"]["requirements"]["smokeTestSpecified"] is False
    assert all("-n" in cmd for cmd in snakemake_commands)


def test_tool_validation_smoke_fixture_only_requires_required_inputs(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    add_registered_tool(
        cfg,
        {
            "id": "conda-forge::optional-input-smoke",
            "name": "optional-input-smoke",
            "source": "conda-forge",
            "packageSpec": "conda-forge::optional-input-smoke=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [
                    {"name": "primary", "type": "file", "required": True},
                    {"name": "auxiliary", "type": "file", "required": False},
                ],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                **_rule_contract_fields(),
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::optional-input-smoke=9.5"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )
    run_configs: list[dict[str, object]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        config_path = Path(cmd[cmd.index("--configfile") + 1])
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_configs.append(run_config)
        if "-n" not in cmd:
            output = Path(run_config["outputs"]["report"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    with patch("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run):
        checked = _validate_registered_tool(cfg, "conda-forge::optional-input-smoke")

    assert checked["contractStatus"]["smokeRun"]["status"] == "passed"
    assert checked["contractStatus"]["outputValidation"]["status"] == "passed"
    assert checked["toolContract"]["smokeTest"]["missingInputs"] == []
    assert checked["toolContract"]["state"] == "WorkflowReady"
    assert all("auxiliary" not in run_config["workflow"]["steps"][0]["inputs"] for run_config in run_configs)


def test_tool_validation_auto_binds_single_matching_smoke_database(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    database_dir = tmp_path / "bracken-db"
    database_dir.mkdir()
    for filename in ["hash.k2d", "opts.k2d", "taxo.k2d", "database100mers.kmer_distrib"]:
        (database_dir / filename).write_text("db\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_bracken",
            "name": "Bracken smoke DB",
            "type": "taxonomy",
            "version": "smoke",
            "path": str(database_dir),
            "metadata": {"templateId": "bracken"},
            "status": "available",
        },
    )
    fields = _rule_contract_fields()
    add_registered_tool(
        cfg,
        {
            "id": "bioconda::db-smoke",
            "name": "db-smoke",
            "source": "bioconda",
            "packageSpec": "bioconda::db-smoke=1.0",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf 'ok\\n' > {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {
                    **fields["resources"],
                    "bracken_db": {
                        "type": "database",
                        "required": True,
                        "acceptedTemplates": ["bracken"],
                        "configKey": "bracken_db",
                    },
                },
                "log": fields["log"],
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["bioconda::db-smoke=1.0"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
        },
    )
    run_configs: list[dict[str, object]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        config_path = Path(cmd[cmd.index("--configfile") + 1])
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_configs.append(run_config)
        if "-n" not in cmd:
            output = Path(run_config["outputs"]["report"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    with patch("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run):
        checked = _validate_registered_tool(cfg, "bioconda::db-smoke")

    assert checked["toolContract"]["state"] == "WorkflowReady"
    assert all(run_config["databases"]["bracken_db"] == str(database_dir) for run_config in run_configs)
    assert all(run_config["resources"]["bracken_db"]["databaseId"] == "db_bracken" for run_config in run_configs)
