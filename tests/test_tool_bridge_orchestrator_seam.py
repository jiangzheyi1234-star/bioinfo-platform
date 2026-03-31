from core.execution.tool_bridge_service import ToolBridgeService


def test_tool_bridge_service_execute_tool_comes_from_orchestrator_module():
    assert ToolBridgeService.execute_tool.__module__ == "core.execution.tool_bridge_execution_orchestrator"
