from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from apps.api.tool_profiles import resolve_tool_profile
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database, check_reference_database
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.tool_prepare_job_storage import create_tool_prepare_job, fetch_tool_prepare_job
from apps.remote_runner.tool_prepare_jobs import run_tool_prepare_job
from apps.remote_runner.tool_preparation import validate_registered_tool_for_publish
from apps.remote_runner.tool_revisions import publish_tool_revision
from apps.remote_runner.tools import ToolRegistryError
from tests.test_tool_contract_pipeline import _cfg, _rule_contract_fields, _runtime_commands


def test_prepare_job_publish_validates_unsaved_candidate_before_persisting(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    snakemake_commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        snakemake_commands.append(list(cmd))
        if "-n" not in cmd:
            config_path = Path(cmd[cmd.index("--configfile") + 1])
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            assert run_config["tool"]["id"] == "conda-forge::prepare-unsaved"
            output = Path(run_config["outputs"]["report"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)

    saved = _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-unsaved", "prepare-unsaved"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-unsaved")["contractStatus"]["smokeRun"]["status"] == "passed"
    assert any("-n" in cmd for cmd in snakemake_commands)
    assert any("-n" not in cmd for cmd in snakemake_commands)


def test_prepare_job_publish_does_not_persist_failed_validation(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)

    def fake_validation(_cfg, _tool):
        return {
            "ok": False,
            "message": "Smoke test input fixtures are required.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {
                    "status": "failed",
                    "code": "TOOL_RULE_SMOKE_TEST_REQUIRED",
                    "message": "Smoke test input fixtures are required.",
                },
                "outputValidation": {"status": "not_run", "message": ""},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    try:
        _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-fails", "prepare-fails"))
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_SMOKE_TEST_REQUIRED"
    else:
        raise AssertionError("failed prepare must raise and not persist the tool")

    assert fetch_tool(cfg, "conda-forge::prepare-fails") is None


def test_prepare_job_publish_persists_only_after_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)

    def fake_validation(_cfg, _tool):
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    saved = _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-ready", "prepare-ready"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-ready")["contractStatus"]["outputValidation"]["status"] == "passed"


def test_h2ometa_profile_prepare_payload_publishes_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "latestVersion": "0.24.1",
        }
    )
    assert draft is not None

    def fake_validation(_cfg, tool):
        assert tool["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
        assert tool["ruleSpecDraft"]["requiresUserCompletion"] is False
        assert tool["ruleTemplate"]["wrapper"] == "v9.8.0/bio/fastp"
        assert tool["ruleTemplate"]["outputs"][0]["name"] == "trimmed"
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    saved = _publish_tool_candidate(
        cfg,
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.24.1",
            "packageSpec": "bioconda::fastp=0.24.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    assert saved["status"] == "published"
    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert saved["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert fetch_tool(cfg, "bioconda::fastp")["toolContract"]["workflowReady"] is True


def test_h2ometa_profile_prepare_job_result_is_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "latestVersion": "0.24.1",
        }
    )
    assert draft is not None

    def fake_validation(_cfg, tool, event_callback=None):
        assert tool["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
        assert tool["ruleSpecDraft"]["requiresUserCompletion"] is False
        if event_callback is not None:
            event_callback({"stage": "runtime_check", "message": "Workflow runtime check passed.", "level": "success"})
            event_callback({"stage": "dry_run", "message": "Snakemake dry-run passed.", "level": "success"})
            event_callback({"stage": "smoke_run", "message": "Snakemake smoke run passed.", "level": "success"})
            event_callback({"stage": "output_validation", "message": "Output validation passed.", "level": "success"})
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.24.1",
            "packageSpec": "bioconda::fastp=0.24.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["stage"] == "published"
    assert finished["result"]["toolContract"]["state"] == "WorkflowReady"
    assert finished["result"]["toolContract"]["workflowReady"] is True
    assert finished["result"]["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert {event["stage"] for event in finished["events"]} >= {
        "validating_spec",
        "profile_schema_validation",
        "static_rulespec_validation",
        "environment_resolution",
        "runtime_check",
        "dry_run",
        "smoke_run",
        "output_validation",
        "published",
    }
    assert fetch_tool(cfg, "bioconda::fastp")["toolContract"]["workflowReady"] is True


def test_h2ometa_database_profile_prepare_auto_binds_single_matching_database(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    database_dir = tmp_path / "kraken2-db"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text("db\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2 smoke DB",
            "templateId": "kraken2",
            "path": str(database_dir),
        },
    )
    checked_database = check_reference_database(cfg, "db_kraken2")
    assert checked_database["status"] == "available"
    draft = resolve_tool_profile(
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "latestVersion": "2.1.3",
        }
    )
    assert draft is not None

    run_configs: list[dict[str, object]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        config_path = Path(cmd[cmd.index("--configfile") + 1])
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_configs.append(run_config)
        if "-n" not in cmd:
            for output_path in run_config["outputs"].values():
                output = Path(str(output_path))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_validation.subprocess.run", fake_run)

    saved = _publish_tool_candidate(
        cfg,
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.1.3",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert run_configs
    assert all(run_config["databases"]["kraken2_db"] == str(database_dir) for run_config in run_configs)
    assert all(run_config["resourceConfig"]["kraken2_db"] == str(database_dir) for run_config in run_configs)
    assert all(run_config["resources"]["kraken2_db"]["databaseId"] == "db_kraken2" for run_config in run_configs)


def test_tool_prepare_is_exposed_through_api_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_main = (root / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (root / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    frontend_api = (root / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")
    frontend_state = (root / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    assert '@router.post("/api/v1/tools/prepare-jobs", status_code=202)' in remote_route
    assert '@app.post("/api/v1/tools/prepare-jobs", status_code=202)' in local_main
    assert "def create_tool_prepare_job" in proxy
    assert 'client.post_json("/api/v1/tools/prepare-jobs"' in proxy
    assert "def create_tool_prepare_job" in runner_ops
    assert '"/api/v1/tools/prepare-jobs"' in frontend_api
    assert '"/api/v1/tools"' in frontend_api
    assert "addToolDependency(nextTool)" in frontend_state
    assert "createToolPrepareJob(nextTool)" in frontend_state


def _publish_tool_candidate(cfg, payload: dict[str, object]) -> dict[str, object]:
    item = validate_registered_tool_for_publish(cfg, payload)
    published = publish_tool_revision(cfg, item)
    published["status"] = "published"
    published["message"] = str(item.get("message") or "Tool revision published.")
    return upsert_tool(cfg, published)


def _prepare_tool_payload(tool_id: str, name: str) -> dict[str, object]:
    return {
        "id": tool_id,
        "name": name,
        "source": "conda-forge",
        "packageSpec": f"conda-forge::{name}=1.0",
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
                    "dependencies": [f"conda-forge::{name}=1.0"],
                }
            },
            "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
        },
    }
