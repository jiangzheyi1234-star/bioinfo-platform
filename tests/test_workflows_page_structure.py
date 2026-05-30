from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def test_workflows_page_uses_live_builder_modules() -> None:
    page = (COMPONENTS / "workflows-page.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    local_api = (ROOT / "apps" / "api" / "main.py").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    readiness = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")

    assert "const workflowTemplates = [" not in page
    assert "requestLocalApiJson" not in page
    assert "useWorkflowsPageState" in page
    assert "fetchWorkflowTemplates" not in api
    assert '"/api/v1/runs"' in api
    assert '"/api/v1/uploads"' in api
    assert "/api/v1/servers" in api
    assert "serverId" in api
    assert "contentBase64" in api
    assert "generated-tool-run-v1" in model
    assert "ruleReadyToolScore" in model
    assert "WORKFLOW_TOOL_NOT_READY" in model
    assert "所选工具还未通过合同验证" in model
    assert "commandTemplate" in readiness
    assert "ruleActionFields(template)" in readiness
    assert "wrapperRefLocked" in readiness
    assert "targetPlatformSupported === true" in readiness
    assert "ruleSpecReadinessForTool(entry.tool).workflowReady" in model
    assert "buildGeneratedWorkflowRunSpec" in api
    check_tool_route = local_api[
        local_api.index('@app.post("/api/v1/tools/{tool_id}/check")') :
        local_api.index('@app.get("/api/v1/databases")')
    ]
    assert 'await invalidate_response_cache("tools", "workflow_catalog")' in check_tool_route
    assert "export function useWorkflowsPageState" in hook
    assert "export { WorkflowCatalogTable }" in ui
    assert "export function WorkflowRunBuilder" in ui


def test_generated_workflow_builder_has_explicit_dag_contract() -> None:
    model_path = COMPONENTS / "generated-workflow-model.ts"
    hook_path = COMPONENTS / "use-generated-workflow-builder.ts"
    ui_path = COMPONENTS / "generated-workflow-builder.tsx"
    graph_node_path = COMPONENTS / "generated-workflow-graph-node-card.tsx"
    graph_canvas_path = COMPONENTS / "generated-workflow-graph-canvas.tsx"
    node_settings_path = COMPONENTS / "generated-workflow-node-settings.tsx"
    command_contract_path = COMPONENTS / "generated-workflow-command-contract.ts"
    param_contract_path = COMPONENTS / "generated-workflow-param-contract.ts"
    port_contract_path = COMPONENTS / "generated-workflow-port-contract.ts"
    recommendation_contract_path = COMPONENTS / "generated-workflow-recommendation-contract.ts"
    rule_action_contract_path = COMPONENTS / "generated-workflow-rule-action-contract.ts"
    snakefile_preview_path = COMPONENTS / "generated-workflow-snakefile-preview.tsx"
    runtime_contract_path = COMPONENTS / "generated-workflow-runtime-contract.ts"
    rule_spec_panel_path = COMPONENTS / "generated-workflow-rule-spec-panel.tsx"
    step_params_editor_path = COMPONENTS / "generated-workflow-step-params-editor.tsx"
    runtime_editor_path = COMPONENTS / "generated-workflow-runtime-editor.tsx"
    port_bindings_editor_path = COMPONENTS / "generated-workflow-port-bindings-editor.tsx"
    page_model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    page_hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    page_ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")
    detail_page = (COMPONENTS / "workflow-detail-page.tsx").read_text(encoding="utf-8")

    assert model_path.exists()
    assert hook_path.exists()
    assert ui_path.exists()
    assert graph_node_path.exists()
    assert graph_canvas_path.exists()
    assert node_settings_path.exists()
    assert command_contract_path.exists()
    assert param_contract_path.exists()
    assert port_contract_path.exists()
    assert recommendation_contract_path.exists()
    assert rule_action_contract_path.exists()
    assert snakefile_preview_path.exists()
    assert runtime_contract_path.exists()
    assert rule_spec_panel_path.exists()
    assert step_params_editor_path.exists()
    assert runtime_editor_path.exists()
    assert port_bindings_editor_path.exists()

    model = model_path.read_text(encoding="utf-8")
    builder_hook = hook_path.read_text(encoding="utf-8")
    builder_ui = ui_path.read_text(encoding="utf-8")
    graph_node_ui = graph_node_path.read_text(encoding="utf-8")
    graph_canvas_ui = graph_canvas_path.read_text(encoding="utf-8")
    node_settings_ui = node_settings_path.read_text(encoding="utf-8")
    command_contract = command_contract_path.read_text(encoding="utf-8")
    param_contract = param_contract_path.read_text(encoding="utf-8")
    port_contract = port_contract_path.read_text(encoding="utf-8")
    recommendation_contract = recommendation_contract_path.read_text(encoding="utf-8")
    rule_action_contract = rule_action_contract_path.read_text(encoding="utf-8")
    snakefile_preview_ui = snakefile_preview_path.read_text(encoding="utf-8")
    runtime_contract = runtime_contract_path.read_text(encoding="utf-8")
    rule_spec_panel_ui = rule_spec_panel_path.read_text(encoding="utf-8")
    step_params_editor_ui = step_params_editor_path.read_text(encoding="utf-8")
    runtime_editor_ui = runtime_editor_path.read_text(encoding="utf-8")
    port_bindings_editor_ui = port_bindings_editor_path.read_text(encoding="utf-8")

    assert "export type GeneratedWorkflowDraft" in model
    assert "GENERATED_WORKFLOW_RULE_CONTRACT_VERSION" in model
    assert "export type GeneratedWorkflowStepRuntime" in model
    assert "export type GeneratedWorkflowGraphDraft" in model
    assert "export type GeneratedWorkflowGraphNode" in model
    assert "export type GeneratedWorkflowGraphEdge" in model
    assert "temp?: boolean" in model
    assert "protected?: boolean" in model
    assert "directory?: boolean" in model
    assert "path?: string" in model
    assert "readOutputSemantics" in model
    assert "outputSemanticTags" in model
    assert "steps: []" in model
    assert "steps: first ? [createStepDraft(first, [])] : []" not in model
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
    readiness = (COMPONENTS / "tool-rule-readiness.ts").read_text(encoding="utf-8")
    assert "tool.ruleSpecDraft" in readiness
    assert "draft?.ruleTemplate" in readiness
    assert "readToolRuleSpecDraft" not in model
    assert "hasRuleAction" not in model
    assert "validateGeneratedWorkflowDraft" in model
    assert "portsCompatible" in model
    assert "portCompatibilityScore" in model
    assert "findCompatibleOutputBinding" in model
    assert "capabilityPortsForTool" not in model
    assert "capabilitySlotForRulePort" not in port_contract
    assert "capabilityPortItemsForTool" not in port_contract
    assert "tool?.capabilities" not in port_contract
    assert "WORKFLOW_STEP_INPUT_OUTPUT_INCOMPATIBLE" in model
    assert "WORKFLOW_STEP_INPUT_PORT_UNKNOWN" in model
    assert "declaredInputNames" in model
    assert "WORKFLOW_OUTPUT_ALIAS_DUPLICATE" in model
    assert "WORKFLOW_OUTPUT_TEMP_EXPOSED" in model
    assert "WORKFLOW_STEP_OUTPUT_PATH_REQUIRED" in model
    assert "outputIsExposable" in model
    assert "validateDefaultExposedOutputs" in model
    assert "validateStepCommandPortBindings" in model
    assert "commandPortReferences" in command_contract
    assert "commandRuntimeReferences" in command_contract
    assert "WORKFLOW_STEP_INPUT_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_INPUT_TOKEN_UNBOUND" in command_contract
    assert "WORKFLOW_STEP_OUTPUT_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_THREADS_TOKEN_UNBOUND" in command_contract
    assert "WORKFLOW_STEP_RESOURCE_TOKEN_UNKNOWN" in command_contract
    assert "WORKFLOW_STEP_LOG_TOKEN_UNKNOWN" in command_contract
    assert "inputBindings" in command_contract
    assert "runtimeDefaultsForRuleTemplate" in command_contract
    assert "validateStepParamBindings" in model
    assert "validateStepRuntime" in model
    assert "readPortCompatibility" in port_contract
    assert "describePortCompatibility" in port_contract
    assert "export type RulePortRecommendationDecision" in recommendation_contract
    assert "export type RulePortRecommendation" in recommendation_contract
    assert "decision: RulePortRecommendationDecision" in recommendation_contract
    assert "hardChecks: string[]" in recommendation_contract
    assert "evidence: string[]" in recommendation_contract
    assert "confidence: number" in recommendation_contract
    assert "explainPortRecommendation" in recommendation_contract
    assert "isAutoBindablePortRecommendation" in recommendation_contract
    assert "export type RulePortEdgeAudit" in recommendation_contract
    assert "autoEdgeAudit" in recommendation_contract
    assert "manualEdgeAudit" in recommendation_contract
    assert 'source: "auto"' in recommendation_contract
    assert 'source: "manual"' in recommendation_contract
    assert "类型证据不足，保留为手动连接" in recommendation_contract
    assert '"recommended"' in recommendation_contract
    assert '"blocked"' in recommendation_contract
    assert '"ambiguous"' in recommendation_contract
    assert "validateRuleActionContract" in model
    assert "isAutoBindablePortRecommendation" in model
    assert "explainPortRecommendation(input, output)" in model
    assert "export function readToolRuleTemplate" in model
    assert "WORKFLOW_RULE_ACTION_REQUIRED" in rule_action_contract
    assert "WORKFLOW_RULE_ACTION_CONFLICT" in rule_action_contract
    assert '["commandTemplate", "wrapper", "script", "module"]' in rule_action_contract
    assert "runSpec.workflow = {" in model
    assert "audit?: RulePortEdgeAudit" in model
    assert "audit: edge.audit" in model
    assert "audit: binding.audit" in model
    assert "contractVersion:" in model
    assert "nodes: draft.nodes.map" in model
    assert "edges: draft.edges.map" in model
    assert "outputs: draft.exposeOutputs.map" in model
    assert "runtime: normalizeStepRuntime" in model
    assert "ruleSpecDraft: readToolRuleSpecDraft(tool)" not in model
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
    assert "audit: manualEdgeAudit()" in builder_hook

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
    assert "GeneratedWorkflowSnakefilePreview" in builder_ui
    assert "GeneratedWorkflowGraphSnakefilePreview" in builder_ui
    assert "selectedNode.params" in builder_ui
    assert "export function GeneratedWorkflowRuleSpecPanel" in rule_spec_panel_ui
    assert "commandTemplate" in rule_spec_panel_ui
    assert "ruleTemplateForTool" in rule_spec_panel_ui
    assert "moduleActionDisplay" in rule_spec_panel_ui
    assert "module:" in rule_spec_panel_ui
    assert "readRuleSpecProvenance" in rule_spec_panel_ui
    assert "ruleSpecDraft" in rule_spec_panel_ui
    assert "wrapperRef" in rule_spec_panel_ui
    assert "wrapperPath" in rule_spec_panel_ui
    assert "wrapperIdentifier" in rule_spec_panel_ui
    assert "parseWrapperIdentifier" in rule_spec_panel_ui
    assert "Object.keys(objectValue(template.module)).length > 0" in rule_spec_panel_ui
    assert "snakemakeWrappers" in rule_spec_panel_ui
    assert "官方 wrapper 已锁定" in rule_spec_panel_ui
    assert "environment" in rule_spec_panel_ui
    assert "RuleSpecContractSummary" in rule_spec_panel_ui
    assert "输入端口" in rule_spec_panel_ui
    assert "输出端口" in rule_spec_panel_ui
    assert "参数默认值" in rule_spec_panel_ui
    assert "调度资源 / log" in rule_spec_panel_ui
    assert "formatRuleOutputSemantics" in rule_spec_panel_ui
    assert "export function GeneratedWorkflowSnakefilePreview" in snakefile_preview_ui
    assert "export function GeneratedWorkflowGraphSnakefilePreview" in snakefile_preview_ui
    assert "Snakefile preview" in snakefile_preview_ui
    assert "Workflow Snakefile preview" in snakefile_preview_ui
    assert "graphPreviewLines" in snakefile_preview_ui
    assert "rulePreviewLines" in snakefile_preview_ui
    assert "rule all:" in snakefile_preview_ui
    assert "inputPathForRulePort" in snakefile_preview_ui
    assert "renderOutputValue" in snakefile_preview_ui
    assert "shell:" in snakefile_preview_ui
    assert "wrapper:" in snakefile_preview_ui
    assert "script:" in snakefile_preview_ui
    assert "module " in snakefile_preview_ui
    assert "use rule" in snakefile_preview_ui
    assert "conda:" in snakefile_preview_ui
    assert "hasRunnableCondaEnvironment" in snakefile_preview_ui
    assert "tool?.selectedPackageSpec || tool?.packageSpec" in snakefile_preview_ui
    assert "GeneratedWorkflowRuntimeEditor" in builder_ui
    assert "GeneratedWorkflowPortBindingsEditor" in builder_ui
    assert "function PortBindingsEditor" not in builder_ui
    assert "export function GeneratedWorkflowPortBindingsEditor" in port_bindings_editor_ui
    assert "PortBindingRow" in port_bindings_editor_ui
    assert "PortBindingValueEditor" in port_bindings_editor_ui
    assert "defaultBinding(nextType, recommendedOutputCandidates)" in port_bindings_editor_ui
    assert "defaultBinding(nextType, compatibleOutputCandidates)" not in port_bindings_editor_ui
    assert "recommendedCandidates[0]" in port_bindings_editor_ui
    assert "manualOnlyCandidate" in port_bindings_editor_ui
    assert "RuleGraphNodeCard" in graph_canvas_ui
    assert "validationIssues={validationIssues" in graph_canvas_ui
    assert "validationIssues={builder.validation.errors}" in builder_ui
    assert "GeneratedWorkflowGraphCanvas" in builder_ui
    assert "export function GeneratedWorkflowGraphCanvas" in graph_canvas_ui
    assert "从工具库添加 RuleSpec 节点" in graph_canvas_ui
    assert "WorkflowGraphEdgeLayer" in graph_canvas_ui
    assert "data-workflow-graph-edge-layer" in graph_canvas_ui
    assert "data-workflow-graph-edge" in graph_canvas_ui
    assert "data-from-port" in graph_canvas_ui
    assert "data-to-port" in graph_canvas_ui
    assert "markerEnd" in graph_canvas_ui
    assert "viewBox" in graph_canvas_ui
    assert "readRuleInputs" in graph_canvas_ui
    assert "readRuleOutputs" in graph_canvas_ui
    assert "portAnchorForEdge" in graph_canvas_ui
    assert "portOffset" in graph_canvas_ui
    assert "edgePath" in graph_canvas_ui
    assert "edges={edges}" in builder_ui
    assert "function RuleGraphNodeCard" not in builder_ui
    assert "export function RuleGraphNodeCard" in graph_node_ui
    assert "RulePortColumn" in graph_node_ui
    assert "GeneratedWorkflowValidationIssue" in graph_node_ui
    assert "unknownInputIssues" in graph_node_ui
    assert "data-port-error" in graph_node_ui
    assert "data-node-state" in graph_node_ui
    assert "未知输入端口" in graph_node_ui
    assert "portBindingState" in graph_node_ui
    assert "outputFanoutCount" in graph_node_ui
    assert "data-port-state" in graph_node_ui
    assert "已连接" in graph_node_ui
    assert "待绑定" in graph_node_ui
    assert "fan-out" in graph_node_ui
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
    assert "工具库" in builder_ui
    assert "RulePaletteCard" in builder_ui
    assert "规则节点库" not in builder_ui
    assert "ruleActionLabelForTool" in builder_ui
    assert "rulePortsLabelForTool" in builder_ui
    assert "ruleEnvironmentLabelForTool" in builder_ui
    assert "RuleSpec 节点" in builder_ui
    assert "运行环境" in builder_ui
    assert "Inspector" in builder_ui
    assert "GeneratedWorkflowPortBindingsEditor" in builder_ui
    assert "function InputBindingRow" not in builder_ui
    assert "builder.draft.steps.map((step, index)" not in builder_ui
    assert "Step {index + 1}" not in builder_ui
    assert "inputCount={inputCount}" in builder_ui
    assert "上传文件" in port_bindings_editor_ui
    assert "输入 role" in port_bindings_editor_ui
    assert "直接路径" in port_bindings_editor_ui
    assert "removeGraphEdge" in builder_ui
    assert "builder.removeStep(selectedNode.id)" in builder_ui
    assert "删除节点" in builder_ui
    assert "删除连线" in builder_ui
    assert "EdgeAuditBadge" in builder_ui
    assert "自动推荐" in builder_ui
    assert "手动连接" in builder_ui
    assert "edgeForInput" in port_bindings_editor_ui
    assert "compatibleOutputCandidates" in port_bindings_editor_ui
    assert "recommendedOutputCandidates" in port_bindings_editor_ui
    assert "candidate.recommendation?.decision === \"recommended\"" in port_bindings_editor_ui
    assert "compatibilityReason" in port_bindings_editor_ui
    assert "explainPortRecommendation" in port_bindings_editor_ui
    assert "recommendation.evidence" in port_bindings_editor_ui
    assert "recommendation.confidence" in port_bindings_editor_ui
    assert "推荐原因" in port_bindings_editor_ui
    assert "推荐证据" in port_bindings_editor_ui
    assert "手动连接提示" in port_bindings_editor_ui
    assert "confidence" in port_bindings_editor_ui
    assert "compatibilityScore" in port_bindings_editor_ui
    assert "应用推荐" in port_bindings_editor_ui
    assert "autoEdgeAudit(recommended.recommendation)" in port_bindings_editor_ui
    assert "（推荐）" in port_bindings_editor_ui
    assert "解绑" in port_bindings_editor_ui
    assert "Select" in port_bindings_editor_ui
    assert "Alert" in builder_ui
    assert "fromStep" in builder_ui
    assert "portsCompatible" in port_bindings_editor_ui
    assert "不兼容" in port_bindings_editor_ui
    assert "exposeOutputs" in builder_ui
    assert "script:" in builder_ui
    assert "module:" in builder_ui

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
