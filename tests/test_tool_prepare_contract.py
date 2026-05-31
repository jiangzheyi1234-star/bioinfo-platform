from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.tool_preparation import prepare_registered_tool
from apps.remote_runner.tools import ToolRegistryError
from tests.test_tool_contract_pipeline import _cfg, _rule_contract_fields, _runtime_commands


def test_prepare_registered_tool_validates_unsaved_candidate_before_persisting(monkeypatch, tmp_path: Path) -> None:
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

    saved = prepare_registered_tool(cfg, _prepare_tool_payload("conda-forge::prepare-unsaved", "prepare-unsaved"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-unsaved")["contractStatus"]["smokeRun"]["status"] == "passed"
    assert any("-n" in cmd for cmd in snakemake_commands)
    assert any("-n" not in cmd for cmd in snakemake_commands)


def test_prepare_registered_tool_does_not_persist_failed_validation(monkeypatch, tmp_path: Path) -> None:
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
        prepare_registered_tool(cfg, _prepare_tool_payload("conda-forge::prepare-fails", "prepare-fails"))
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_SMOKE_TEST_REQUIRED"
    else:
        raise AssertionError("failed prepare must raise and not persist the tool")

    assert fetch_tool(cfg, "conda-forge::prepare-fails") is None


def test_prepare_registered_tool_persists_only_after_workflow_ready(monkeypatch, tmp_path: Path) -> None:
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

    saved = prepare_registered_tool(cfg, _prepare_tool_payload("conda-forge::prepare-ready", "prepare-ready"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-ready")["contractStatus"]["outputValidation"]["status"] == "passed"


def test_tool_prepare_is_exposed_through_api_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    local_main = (root / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (root / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    frontend_api = (root / "apps" / "web" / "app" / "components" / "tools-page-api.ts").read_text(encoding="utf-8")
    frontend_state = (root / "apps" / "web" / "app" / "components" / "use-tools-page-state.ts").read_text(encoding="utf-8")
    assert '@router.post("/api/v1/tools/prepare", status_code=201)' in remote_route
    assert "await run_in_threadpool(prepare_registered_tool" in remote_route
    assert '@app.post("/api/v1/tools/prepare", status_code=201)' in local_main
    assert "def prepare_tool" in proxy
    assert 'client.post_json("/api/v1/tools/prepare"' in proxy
    assert "def prepare_tool" in runner_ops
    assert '"/api/v1/tools/prepare"' in frontend_api
    assert '"/api/v1/tools"' in frontend_api
    assert "addToolDependency(nextTool)" in frontend_state
    assert "prepareToolDependency(nextTool)" in frontend_state


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
