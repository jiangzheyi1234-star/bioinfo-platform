from __future__ import annotations

from pathlib import Path

from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.generated_workflow import (
    GENERATED_TOOL_RUN_PIPELINE_ID,
    prepare_generated_tool_workflow,
)
from apps.remote_runner.tools import add_registered_tool
from tests.helpers.tool_contract_pipeline import _cfg, _reads


def test_generated_workflow_cannot_bypass_registered_contract_with_request_rulespec(
    tmp_path: Path,
) -> None:
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
        assert str(exc) == "WORKFLOW_GRAPH_NODE_UNSUPPORTED_FIELD: run_tool.tool"
    else:
        raise AssertionError("runSpec RuleSpec must not bypass the registered tool contract")


def test_tool_production_acceptance_is_exposed_through_api_layers() -> None:
    root = Path(__file__).resolve().parents[1]
    remote_main = (root / "apps" / "remote_runner" / "main.py").read_text(encoding="utf-8")
    remote_route = (root / "apps" / "remote_runner" / "tool_routes.py").read_text(encoding="utf-8")
    remote_service = (root / "apps" / "remote_runner" / "tool_service.py").read_text(encoding="utf-8")
    local_main = (root / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    local_route = (root / "apps" / "api" / "tool_contract_routes.py").read_text(encoding="utf-8")
    local_service = (root / "apps" / "api" / "tool_contract_service.py").read_text(encoding="utf-8")
    proxy = (root / "core" / "remote_runner" / "proxy.py").read_text(encoding="utf-8")
    runner_ops = (root / "core" / "app_runtime" / "runner_ops.py").read_text(encoding="utf-8")
    runner_tool_ops = (root / "core" / "app_runtime" / "runner_tool_ops.py").read_text(encoding="utf-8")
    tool_manager = (root / "core" / "app_runtime" / "managers" / "tool.py").read_text(encoding="utf-8")

    assert "tool_router" in remote_main
    assert "operation_id=REMOTE_ENDPOINTS[TOOL_PRODUCTION_ENABLE].operation_id" in remote_route
    assert "mark_tool_production_from_request" in remote_route
    assert "mark_registered_tool_production_enabled" in remote_service
    assert "request_payload(payload)" in remote_service
    assert "tool_contract_router" in local_main
    assert "operation_id=REMOTE_ENDPOINTS[TOOL_PRODUCTION_ENABLE].operation_id" in local_route
    assert "mark_tool_production_from_request" in local_route
    assert 'await invalidate_response_cache("tools", "workflow_catalog")' in local_service
    assert "def mark_tool_production_enabled" not in proxy
    assert "/api/v1/tools/{kwargs['tool_id']}/production" not in proxy
    assert "RunnerToolOperationsMixin" in runner_ops
    assert "def mark_tool_production_enabled" in runner_tool_ops
    assert "def mark_tool_production_enabled" in tool_manager
