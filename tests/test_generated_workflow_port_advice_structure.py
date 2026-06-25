from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_canvas_converter_advice_requires_explicit_confirmation() -> None:
    builder_ui = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    graph_canvas_ui = (COMPONENTS / "generated-workflow-graph-canvas.tsx").read_text(encoding="utf-8")
    port_advice_contract = (COMPONENTS / "generated-workflow-port-advice.ts").read_text(encoding="utf-8")
    port_bindings_editor_ui = (COMPONENTS / "generated-workflow-port-bindings-editor.tsx").read_text(encoding="utf-8")

    assert "export function converterSuggestionsForInput" in port_advice_contract
    assert "export function converterSuggestionsForConnection" in port_advice_contract
    assert "automaticConverterInsertionRequestForConnection" not in port_advice_contract
    assert "automatic-unambiguous" not in port_advice_contract
    assert "targetInputAlreadyBound" not in port_advice_contract
    assert "findOneHopPortConverters" in port_advice_contract
    assert "backendPlanConverterInsertionForSuggestion" in port_advice_contract
    assert "insertionRequestForBackendCandidate" in port_advice_contract
    assert "portsCompatible(input, output)" in port_advice_contract
    assert "wouldCreateCycle" in port_advice_contract

    assert "onInsertConverter={builder.insertConverter}" in builder_ui
    assert "semanticPortPlan={semanticPortPlan}" in builder_ui
    assert "automaticConverterInsertionRequestForConnection" not in graph_canvas_ui
    assert "converterSuggestionsForConnection" in graph_canvas_ui
    assert "connectionNoticeForDecision" in graph_canvas_ui
    assert "RulePortConverterInsertionRequest" in graph_canvas_ui
    assert 'data-testid="workflow-graph-connection-notice"' in graph_canvas_ui
    assert 'data-connection-notice-code={connectionNotice.code || ""}' in graph_canvas_ui
    assert "data-connection-notice-state={connectionNoticeState(connectionNotice)}" in graph_canvas_ui
    assert 'data-converter-insert-enabled={connectionNotice.request ? "true" : "false"}' in graph_canvas_ui
    assert "code: decision.code" in graph_canvas_ui
    assert 'return "backend-plan-confirmable"' in graph_canvas_ui
    assert 'return "advisory-only"' in graph_canvas_ui
    assert "确认插入转换" in graph_canvas_ui
    assert "需确认，不会自动插入" in graph_canvas_ui
    assert "保存并验证后可使用后端转换建议" in graph_canvas_ui
    assert "backendPlanConverterInsertionForSuggestion" in graph_canvas_ui
    assert "request: backendInsertion?.request" in graph_canvas_ui
    assert "已自动插入转换节点" not in graph_canvas_ui
    assert "将替换当前目标输入绑定" in graph_canvas_ui
    assert "lastInvalidConnectionRef.current = null" in graph_canvas_ui
    assert "setConnectionNotice((current) => (current?.request ? null : current))" in graph_canvas_ui
    assert "onInsertConverter(connectionNotice.request)" in graph_canvas_ui
    assert graph_canvas_ui.count("onInsertConverter(connectionNotice.request)") == 1
    assert "buildConverterInsertionPatch" not in graph_canvas_ui

    on_connect_body = graph_canvas_ui.split("const onConnect = useCallback", 1)[1].split("const onConnectEnd", 1)[0]
    on_connect_end_body = graph_canvas_ui.split("const onConnectEnd", 1)[1].split("const onNodesChange", 1)[0]
    assert "onInsertConverter" not in on_connect_body
    assert "onInsertConverter" not in on_connect_end_body

    assert "generated-workflow-port-advice" in port_bindings_editor_ui
    assert "converterSuggestionsForInput" in port_bindings_editor_ui
    assert "backendPlanConverterInsertionForSuggestion" in port_bindings_editor_ui
    assert "onInsertConverter(backendInsertion.request)" in port_bindings_editor_ui
    assert "onInsertConverter(suggestion)" not in port_bindings_editor_ui
    assert "保存并验证后可使用后端转换建议" in port_bindings_editor_ui
    assert "findOneHopPortConverters" not in port_bindings_editor_ui
