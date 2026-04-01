import core.execution.tool_bridge_service as tool_bridge_service_module
from core.execution.tool_bridge_service import ToolBridgeService
from core.execution.tool_bridge_types import ExecutionResult


def test_tool_bridge_service_execute_tool_comes_from_orchestrator_module():
    assert ToolBridgeService.execute_tool.__module__ == "core.execution.tool_bridge_execution_orchestrator"


def test_tool_bridge_service_execute_tool_preserves_orchestrator_result_shape():
    service = ToolBridgeService()

    result = service.execute_tool("fastp", {})

    assert isinstance(result, ExecutionResult)
    assert result.status == "error"
    assert result.message == "服务未就绪"
    assert result.execution_id == ""
    assert result.sample_id == ""


def test_tool_bridge_service_result_builder_wrapper_forwards_arguments(monkeypatch):
    service = ToolBridgeService()
    execution_row = {"execution_id": "exec_demo", "tool_id": "fastp"}
    captured: dict[str, object] = {}
    sentinel = {"feature_id": "fastp", "archetype": "qc_report"}

    def _fake_builder(self, execution_id, row):
        captured["self"] = self
        captured["execution_id"] = execution_id
        captured["row"] = row
        return sentinel

    monkeypatch.setattr(tool_bridge_service_module, "_tb_build_result_view_for_execution", _fake_builder)

    payload = service._build_result_view_for_execution("exec_demo", execution_row)

    assert payload is sentinel
    assert captured == {
        "self": service,
        "execution_id": "exec_demo",
        "row": execution_row,
    }
