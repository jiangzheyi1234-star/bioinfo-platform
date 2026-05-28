from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflows_page_uses_live_builder_modules() -> None:
    page = (COMPONENTS / "workflows-page.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")

    assert "const workflowTemplates = [" not in page
    assert "requestLocalApiJson" not in page
    assert "useWorkflowsPageState" in page
    assert "fetchWorkflowTemplates" in api
    assert '"/api/v1/workflow-templates"' in api
    assert '"/api/v1/runs"' in api
    assert '"/api/v1/uploads"' in api
    assert "/api/v1/servers" in api
    assert "serverId" in api
    assert "contentBase64" in api
    assert "generated-tool-run-v1" in model
    assert "ruleReadyToolScore" in model
    assert "commandTemplate" in model
    assert "targetPlatformSupported === true" in model
    assert "buildGeneratedWorkflowRunSpec" in api
    assert "export function useWorkflowsPageState" in hook
    assert "export { WorkflowCatalogTable }" in ui
    assert "export function WorkflowRunBuilder" in ui


def test_generated_workflow_builder_has_explicit_dag_contract() -> None:
    model_path = COMPONENTS / "generated-workflow-model.ts"
    hook_path = COMPONENTS / "use-generated-workflow-builder.ts"
    ui_path = COMPONENTS / "generated-workflow-builder.tsx"
    graph_node_path = COMPONENTS / "generated-workflow-graph-node-card.tsx"
    runtime_editor_path = COMPONENTS / "generated-workflow-runtime-editor.tsx"
    page_model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    page_hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    page_ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")
    detail_page = (COMPONENTS / "workflow-detail-page.tsx").read_text(encoding="utf-8")

    assert model_path.exists()
    assert hook_path.exists()
    assert ui_path.exists()
    assert graph_node_path.exists()
    assert runtime_editor_path.exists()

    model = model_path.read_text(encoding="utf-8")
    builder_hook = hook_path.read_text(encoding="utf-8")
    builder_ui = ui_path.read_text(encoding="utf-8")
    graph_node_ui = graph_node_path.read_text(encoding="utf-8")
    runtime_editor_ui = runtime_editor_path.read_text(encoding="utf-8")

    assert "export type GeneratedWorkflowDraft" in model
    assert "export type GeneratedWorkflowStepRuntime" in model
    assert "export type GeneratedWorkflowGraphDraft" in model
    assert "export type GeneratedWorkflowGraphNode" in model
    assert "export type GeneratedWorkflowGraphEdge" in model
    assert "temp?: boolean" in model
    assert "protected?: boolean" in model
    assert "directory?: boolean" in model
    assert "readOutputSemantics" in model
    assert "outputSemanticTags" in model
    assert "createGeneratedWorkflowGraphDraft" in model
    assert "generatedWorkflowDraftToGraphDraft" in model
    assert "graphDraftToGeneratedWorkflowDraft" in model
    assert "validateGeneratedWorkflowGraphDraft" in model
    assert "export type GeneratedWorkflowInputBinding" in model
    assert "fromUpload" in model
    assert "fromInput" in model
    assert "fromStep" in model
    assert "exposeOutputs" in model
    assert "buildGeneratedWorkflowRunSpec" in model
    assert "validateGeneratedWorkflowDraft" in model
    assert "portsCompatible" in model
    assert "findCompatibleOutputBinding" in model
    assert "capabilitySlotForRulePort" in model
    assert "slot.primary === true" in model
    assert "fallbackIndex" in model
    assert "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE" in model
    assert "WORKFLOW_OUTPUT_ALIAS_DUPLICATE" in model
    assert "capabilities" in model
    assert "runSpec.workflow = {" in model
    assert "nodes: draft.nodes.map" in model
    assert "edges: draft.edges.map" in model
    assert "outputs: draft.exposeOutputs.map" in model
    assert "runtime: normalizeStepRuntime" in model
    assert "resourceBindings" in model
    assert "databases" not in model

    assert "useReducer" in builder_hook
    assert "useGeneratedWorkflowBuilder" in builder_hook
    assert "graphDraft" in builder_hook
    assert "findCompatibleOutputBinding" in builder_hook
    assert "validation" in builder_hook
    assert "resourceBindings" in builder_hook
    assert "setStepRuntime" in builder_hook

    assert "GeneratedWorkflowBuilder" in builder_ui
    assert "WorkflowGraphWorkbench" in builder_ui
    assert "GeneratedWorkflowRuntimeEditor" in builder_ui
    assert "RuleGraphNodeCard" in builder_ui
    assert "function RuleGraphNodeCard" not in builder_ui
    assert "export function RuleGraphNodeCard" in graph_node_ui
    assert "RulePortColumn" in graph_node_ui
    assert "输入端口" in graph_node_ui
    assert "输出端口" in graph_node_ui
    assert "data-port-direction" in graph_node_ui
    assert "export function GeneratedWorkflowRuntimeEditor" in runtime_editor_ui
    assert "线程" in runtime_editor_ui
    assert "调度资源" in runtime_editor_ui
    assert "日志" in runtime_editor_ui
    assert "updateLog" in runtime_editor_ui
    assert "logDefaults" in runtime_editor_ui
    assert "namedLogEntries" in runtime_editor_ui
    assert "updateLogPath" in runtime_editor_ui
    assert "未声明 log" in runtime_editor_ui
    assert "builder.graphDraft.nodes" in builder_ui
    assert "selectedNodeId" in builder_ui
    assert "工具 Palette" in builder_ui
    assert "Inspector" in builder_ui
    assert "PortBindingsEditor" in builder_ui
    assert "removeGraphEdge" in builder_ui
    assert "删除连线" in builder_ui
    assert "edgeForInput" in builder_ui
    assert "compatibleOutputCandidates" in builder_ui
    assert "解绑" in builder_ui
    assert "Select" in builder_ui
    assert "Alert" in builder_ui
    assert "fromStep" in builder_ui
    assert "portsCompatible" in builder_ui
    assert "不兼容" in builder_ui
    assert "exposeOutputs" in builder_ui

    assert "buildGeneratedRunSpec" not in page_model
    assert "buildGeneratedWorkflowRunSpec" in api
    assert "type GeneratedWorkflowGraphDraft" in api
    assert "useGeneratedWorkflowBuilder" in page_hook
    assert "draft: generatedBuilder.graphDraft" in page_hook
    assert "GeneratedWorkflowBuilder" in detail_page
    assert "generatedBuilder" in page_ui


def test_tools_page_surfaces_snakemake_wrapper_matches() -> None:
    model = (COMPONENTS / "tools-page-model.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "tools-page-ui.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")

    assert "SnakemakeWrapperMatch" in model
    assert "snakemakeWrappers" in model
    assert "snakemakeWrapperCount" in model
    assert "ruleSpecDraft" in model
    assert "WrapperBadge" in ui
    assert "Snakemake wrapper" in ui
    assert "生成自定义 RuleSpec" in ui
    assert "snakemakeWrappers" in api
    assert "ruleSpecDraft" in api


def test_workflow_sample_data_upload_uses_long_running_timeout() -> None:
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")

    assert "WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "timeoutMs: WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "/api/v1/workflow-sample-data/" in api
