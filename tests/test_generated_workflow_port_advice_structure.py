from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
E2E = ROOT / "tests" / "e2e"


def test_canvas_converter_advice_requires_explicit_confirmation() -> None:
    builder_ui = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    graph_canvas_ui = (COMPONENTS / "generated-workflow-graph-canvas.tsx").read_text(encoding="utf-8")
    graph_notice_contract = (COMPONENTS / "generated-workflow-graph-connection-notice.ts").read_text(encoding="utf-8")
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
    assert "requireProposed?: boolean" in port_advice_contract
    assert "item.proposed === true" in port_advice_contract
    assert "portsCompatible(input, output)" in port_advice_contract
    assert "wouldCreateCycle" in port_advice_contract

    assert "onInsertConverter={builder.insertConverter}" in builder_ui
    assert "semanticPortPlan={semanticPortPlan}" in builder_ui
    assert "onPlanProposedConnection={onPlanProposedConnection}" in builder_ui
    assert "automaticConverterInsertionRequestForConnection" not in graph_canvas_ui
    assert "connectionNoticeForDecision" in graph_canvas_ui
    assert "RulePortConverterInsertionRequest" in graph_canvas_ui
    assert "onPlanProposedConnection" in graph_canvas_ui
    assert "connectionContextSignature" in graph_canvas_ui
    assert "proposedConnectionStaleMessage" in graph_canvas_ui
    assert "WORKFLOW_CONVERTER_INSERTION_STALE" in graph_canvas_ui
    assert "WORKFLOW_CONVERTER_INSERTION_FAILED" in graph_canvas_ui
    assert "requireProposedBackendPlan: true" in graph_canvas_ui
    assert "proposedEdgeForGraphConnection" in graph_notice_contract
    assert "backendPlanConverterInsertionForSuggestion" in graph_notice_contract
    assert "converterSuggestionsForConnection" in graph_notice_contract
    assert "request: backendInsertion?.request" in graph_notice_contract
    assert "requireProposed: requireProposedBackendPlan" in graph_notice_contract
    assert 'data-testid="workflow-graph-connection-notice"' in graph_canvas_ui
    assert 'data-connection-notice-code={connectionNotice.code || ""}' in graph_canvas_ui
    assert "data-connection-notice-state={connectionNoticeState(connectionNotice)}" in graph_canvas_ui
    assert 'data-converter-insert-enabled={connectionNotice.request ? "true" : "false"}' in graph_canvas_ui
    assert "code: decision.code" in graph_notice_contract
    assert 'return "backend-plan-pending"' in graph_notice_contract
    assert 'return "backend-plan-confirmable"' in graph_notice_contract
    assert 'return "advisory-only"' in graph_notice_contract
    assert "确认插入转换" in graph_canvas_ui
    assert "正在请求后端转换建议" in graph_canvas_ui
    assert "需确认，不会自动插入" in graph_notice_contract
    assert "保存并验证后可使用后端转换建议" in graph_canvas_ui
    assert "已自动插入转换节点" not in graph_canvas_ui
    assert "将替换当前目标输入绑定" in graph_notice_contract
    assert "lastInvalidConnectionRef.current = null" in graph_canvas_ui
    assert "连接上下文已变化，请重新拖拽端口以获取新的后端建议。" in graph_canvas_ui
    assert "confirmConverterInsertion(connectionNotice)" in graph_canvas_ui
    assert "onInsertConverter(notice.request)" in graph_canvas_ui
    assert graph_canvas_ui.count("onInsertConverter(notice.request)") == 1
    assert "buildConverterInsertionPatch" not in graph_canvas_ui

    on_connect_body = graph_canvas_ui.split("const onConnect = useCallback", 1)[1].split("const onConnectEnd", 1)[0]
    on_connect_end_body = graph_canvas_ui.split("const onConnectEnd", 1)[1].split("const confirmConverterInsertion", 1)[0]
    assert "onInsertConverter" not in on_connect_body
    assert "onInsertConverter" not in on_connect_end_body

    assert "generated-workflow-port-advice" in port_bindings_editor_ui
    assert "converterSuggestionsForInput" in port_bindings_editor_ui
    assert "backendPlanConverterInsertionForSuggestion" in port_bindings_editor_ui
    assert "onInsertConverter(backendInsertion.request)" in port_bindings_editor_ui
    assert "onInsertConverter(suggestion)" not in port_bindings_editor_ui
    assert "保存并验证后可使用后端转换建议" in port_bindings_editor_ui
    assert "findOneHopPortConverters" not in port_bindings_editor_ui


def test_graph_editor_e2e_proves_backend_planned_converter_confirmation() -> None:
    e2e_spec = (E2E / "generated-workflow-graph-editor.spec.ts").read_text(encoding="utf-8")

    assert 'test("graph editor inserts backend-planned converter only after explicit confirmation"' in e2e_spec
    assert "proposedEdgesSeen" in e2e_spec
    assert "body.proposedEdges?.[0]" in e2e_spec
    assert "semanticPortPlan: semanticPortPlanForConverter(proposedEdge)" in e2e_spec
    assert 'proposed: true' in e2e_spec
    assert 'action: "insert-converter"' in e2e_spec
    assert 'reasonCode: "ONE_HOP_CONVERTER_AVAILABLE"' in e2e_spec
    assert 'insertionMode: "explicit-user-confirmed"' in e2e_spec
    assert 'autoInsertionBlockedReasons: ["confirmation-required", "graph-mutation-requires-user-action"]' in e2e_spec
    assert 'await expect(connectionNotice).toHaveAttribute("data-connection-notice-state", "backend-plan-pending")' in e2e_spec
    assert 'await expect(connectionNotice).toHaveAttribute("data-connection-notice-state", "backend-plan-confirmable"' in e2e_spec
    assert 'await expect(connectionNotice).toHaveAttribute("data-converter-insert-enabled", "true")' in e2e_spec
    assert 'await connectionNotice.getByRole("button", { name: "确认插入转换" }).click()' in e2e_spec
    assert 'await expect(edgeRows).toHaveCount(2' in e2e_spec
    assert 'await expect(edgeRows.filter({ hasText: `${sourceNodeId}.sam` }).filter({ hasText: `${converterNodeId}.sam` })).toHaveCount(1)' in e2e_spec
    assert 'await expect(edgeRows.filter({ hasText: `${converterNodeId}.bam` }).filter({ hasText: `${targetNodeId}.bam` })).toHaveCount(1)' in e2e_spec
    assert 'await expect(edgeRows.filter({ hasText: `${sourceNodeId}.sam` }).filter({ hasText: `${targetNodeId}.bam` })).toHaveCount(0)' in e2e_spec
    assert "E2E SAM to BAM converter" in e2e_spec
