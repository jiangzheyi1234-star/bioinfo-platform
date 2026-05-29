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
    node_settings_path = COMPONENTS / "generated-workflow-node-settings.tsx"
    command_contract_path = COMPONENTS / "generated-workflow-command-contract.ts"
    param_contract_path = COMPONENTS / "generated-workflow-param-contract.ts"
    port_contract_path = COMPONENTS / "generated-workflow-port-contract.ts"
    runtime_contract_path = COMPONENTS / "generated-workflow-runtime-contract.ts"
    rule_spec_panel_path = COMPONENTS / "generated-workflow-rule-spec-panel.tsx"
    step_params_editor_path = COMPONENTS / "generated-workflow-step-params-editor.tsx"
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
    assert node_settings_path.exists()
    assert command_contract_path.exists()
    assert param_contract_path.exists()
    assert port_contract_path.exists()
    assert runtime_contract_path.exists()
    assert rule_spec_panel_path.exists()
    assert step_params_editor_path.exists()
    assert runtime_editor_path.exists()

    model = model_path.read_text(encoding="utf-8")
    builder_hook = hook_path.read_text(encoding="utf-8")
    builder_ui = ui_path.read_text(encoding="utf-8")
    graph_node_ui = graph_node_path.read_text(encoding="utf-8")
    node_settings_ui = node_settings_path.read_text(encoding="utf-8")
    command_contract = command_contract_path.read_text(encoding="utf-8")
    param_contract = param_contract_path.read_text(encoding="utf-8")
    port_contract = port_contract_path.read_text(encoding="utf-8")
    runtime_contract = runtime_contract_path.read_text(encoding="utf-8")
    rule_spec_panel_ui = rule_spec_panel_path.read_text(encoding="utf-8")
    step_params_editor_ui = step_params_editor_path.read_text(encoding="utf-8")
    runtime_editor_ui = runtime_editor_path.read_text(encoding="utf-8")

    assert "export type GeneratedWorkflowDraft" in model
    assert "GENERATED_WORKFLOW_RULE_CONTRACT_VERSION" in model
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
    assert "readToolRuleTemplate" in model
    assert "ruleSpecDraft?.ruleTemplate" in model
    assert "readToolRuleSpecDraft" in model
    assert "hasRuleAction" in model
    assert "validateGeneratedWorkflowDraft" in model
    assert "portsCompatible" in model
    assert "portCompatibilityScore" in model
    assert "findCompatibleOutputBinding" in model
    assert "capabilityPortsForTool" in model
    assert "capabilitySlotForRulePort" in port_contract
    assert "capabilityPortItemsForTool" in port_contract
    assert "export type RulePortCapabilityMetadata" in port_contract
    assert "capabilityId?: string" in port_contract
    assert "capabilityLabel?: string" in port_contract
    assert "tool?.capabilities" in port_contract
    assert "能力来源" in graph_node_ui
    assert "capabilityLabel" in graph_node_ui
    assert "slot.primary === true" in port_contract
    assert "fallbackIndex" in port_contract
    assert "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE" in model
    assert "WORKFLOW_OUTPUT_ALIAS_DUPLICATE" in model
    assert "WORKFLOW_OUTPUT_TEMP_EXPOSED" in model
    assert "outputIsExposable" in model
    assert "validateDefaultExposedOutputs" in model
    assert "validateStepCommandPortBindings" in model
    assert "commandPortReferences" in command_contract
    assert "WORKFLOW_STEP_INPUT_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_OUTPUT_TOKEN_UNKNOWN" in command_contract
    assert "validateStepParamBindings" in model
    assert "validateStepRuntime" in model
    assert "readPortCompatibility" in port_contract
    assert "runSpec.workflow = {" in model
    assert "contractVersion:" in model
    assert "nodes: draft.nodes.map" in model
    assert "edges: draft.edges.map" in model
    assert "outputs: draft.exposeOutputs.map" in model
    assert "runtime: normalizeStepRuntime" in model
    assert "ruleSpecDraft: readToolRuleSpecDraft(tool)" in model
    assert "resourceBindings" in model
    assert "databases" not in model
    assert "WORKFLOW_STEP_PARAM_REQUIRED" in param_contract
    assert "commandParamNames" in param_contract
    assert "export function normalizeStepRuntime" in runtime_contract
    assert "export function validateStepRuntime" in runtime_contract
    assert "WORKFLOW_STEP_THREADS_INVALID" in runtime_contract
    assert "WORKFLOW_STEP_RESOURCES_INVALID" in runtime_contract
    assert "WORKFLOW_STEP_LOG_INVALID" in runtime_contract

    assert "useReducer" in builder_hook
    assert "useGeneratedWorkflowBuilder" in builder_hook
    assert "graphDraft" in builder_hook
    assert "findCompatibleOutputBinding" in builder_hook
    assert "validation" in builder_hook
    assert "resourceBindings" in builder_hook
    assert "setStepRuntime" in builder_hook

    assert "GeneratedWorkflowBuilder" in builder_ui
    assert "WorkflowGraphWorkbench" in builder_ui
    assert "GeneratedWorkflowNodeSettings" in builder_ui
    assert "StepParamsEditor" in builder_ui
    assert "function StepParamsEditor" not in builder_ui
    assert "export function StepParamsEditor" in step_params_editor_ui
    assert "coerceParamValue" in step_params_editor_ui
    assert "export function GeneratedWorkflowNodeSettings" in node_settings_ui
    assert "节点设置" in node_settings_ui
    assert "节点 ID" in node_settings_ui
    assert "onStepIdChange" in node_settings_ui
    assert "onStepToolChange" in node_settings_ui
    assert "GeneratedWorkflowRuleSpecPanel" in builder_ui
    assert "selectedNode.params" in builder_ui
    assert "export function GeneratedWorkflowRuleSpecPanel" in rule_spec_panel_ui
    assert "commandTemplate" in rule_spec_panel_ui
    assert "ruleTemplateForTool" in rule_spec_panel_ui
    assert "readRuleSpecProvenance" in rule_spec_panel_ui
    assert "ruleSpecDraft" in rule_spec_panel_ui
    assert "wrapperRef" in rule_spec_panel_ui
    assert "wrapperPath" in rule_spec_panel_ui
    assert "wrapperIdentifier" in rule_spec_panel_ui
    assert "parseWrapperIdentifier" in rule_spec_panel_ui
    assert "snakemakeWrappers" in rule_spec_panel_ui
    assert "官方 wrapper 已锁定" in rule_spec_panel_ui
    assert "environment" in rule_spec_panel_ui
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
    assert "ruleTemplateForTool" in runtime_editor_ui
    assert "未声明 log" in runtime_editor_ui
    assert "builder.graphDraft.nodes" in builder_ui
    assert "defaultThreadsForTemplate" in runtime_editor_ui
    assert "schedulerResourceDefaults(template)" in runtime_editor_ui
    assert "ruleSpecResourceDefaults" in runtime_editor_ui
    assert "template.resources" in runtime_editor_ui
    assert "selectedNodeId" in builder_ui
    assert "工具 Palette" in builder_ui
    assert "Inspector" in builder_ui
    assert "PortBindingsEditor" in builder_ui
    assert "function InputBindingRow" not in builder_ui
    assert "builder.draft.steps.map((step, index)" not in builder_ui
    assert "Step {index + 1}" not in builder_ui
    assert "inputCount={inputCount}" in builder_ui
    assert "上传文件" in builder_ui
    assert "输入 role" in builder_ui
    assert "直接路径" in builder_ui
    assert "removeGraphEdge" in builder_ui
    assert "builder.removeStep(selectedNode.id)" in builder_ui
    assert "删除节点" in builder_ui
    assert "删除连线" in builder_ui
    assert "edgeForInput" in builder_ui
    assert "compatibleOutputCandidates" in builder_ui
    assert "compatibilityScore" in builder_ui
    assert "应用推荐" in builder_ui
    assert "（推荐）" in builder_ui
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
    assert "!isGeneratedToolRun ? dagPreview : null" in page_ui


def test_tools_page_surfaces_snakemake_wrapper_matches() -> None:
    model = (COMPONENTS / "tools-page-model.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "tools-page-ui.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "tools-page-api.ts").read_text(encoding="utf-8")

    assert "SnakemakeWrapperMatch" in model
    assert "snakemakeWrappers" in model
    assert "snakemakeWrapperCount" in model
    assert "ruleSpecDraft" in model
    assert "syncRuleSpecDraftPackageLock" in model
    assert "applySelectedPackageLock" in model
    assert "WrapperBadge" in ui
    assert "Snakemake wrapper" in ui
    assert "RulePortPreview" in ui
    assert "rulePortItems" in ui
    assert "hasRuleAction" in ui
    assert "formatRulePortLabel" in ui
    assert "输入端口" in ui
    assert "输出端口" in ui
    assert "生成自定义 RuleSpec" in ui
    assert "snakemakeWrappers" in api
    assert "ruleSpecDraft" in api
    hook = (COMPONENTS / "use-tools-page-state.ts").read_text(encoding="utf-8")
    assert "const baseSelected" in hook
    assert "applySelectedPackageLock(baseSelected" in hook


def test_workflow_sample_data_upload_uses_long_running_timeout() -> None:
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")

    assert "WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "timeoutMs: WORKFLOW_SAMPLE_DATA_TIMEOUT_MS" in api
    assert "/api/v1/workflow-sample-data/" in api
