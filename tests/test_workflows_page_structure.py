from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    parameters_start = source.index("(", start)
    parameters_end = _matching_delimiter_end(source, parameters_start, "(", ")")
    brace = source.index("{", parameters_end)
    return _balanced_block(source, brace)


def _type_body(source: str, name: str) -> str:
    start = source.index(f"export type {name} = {{")
    brace = source.index("{", start)
    return _balanced_block(source, brace)


def _matching_delimiter_end(source: str, start: int, open_char: str, close_char: str) -> int:
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError(f"matching {close_char} not found")


def _balanced_block(source: str, brace: int) -> str:
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    raise AssertionError("balanced block not found")


def test_workflows_page_uses_live_builder_modules() -> None:
    page = (COMPONENTS / "workflows-page.tsx").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    generated_model = (COMPONENTS / "generated-workflow-model.ts").read_text(encoding="utf-8")
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
    assert "generated-tool-run-v1" in generated_model
    assert "ruleReadyToolScore" in model
    assert "WORKFLOW_TOOL_NOT_READY" in model
    assert "所选工具还未通过合同验证" in model
    assert "commandTemplate" in readiness
    assert "ruleActionFields(template)" in readiness
    assert "wrapperRefLocked" in readiness
    assert "targetPlatformSupported === true" in readiness
    assert "ruleSpecReadinessForTool(entry.tool).workflowReady" in model
    assert "submitWorkflowDesignRun" in api
    assert "export function useWorkflowsPageState" in hook
    assert "export { WorkflowCatalogTable }" in ui
    assert "export function WorkflowRunBuilder" in ui


def test_generated_workflow_builder_uses_server_tool_recommendations() -> None:
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    builder_ui = (COMPONENTS / "generated-workflow-builder.tsx").read_text(encoding="utf-8")
    recommendations_path = COMPONENTS / "generated-workflow-tool-recommendations.tsx"

    assert recommendations_path.exists()
    recommendations_ui = recommendations_path.read_text(encoding="utf-8")
    assert "export async function fetchWorkflowToolRecommendations" in api
    assert "fetchCapabilityGraphSnapshot" in api
    assert "/api/v1/tool-capabilities/candidate-recommendations" not in api
    assert "workflowRecommendationsFromCapabilityGraph" in api
    assert "agentSelectable === true" in api
    assert "node.capabilityBundle?.capabilityId" in api
    assert "candidateKind: \"capability-bundle\"" in api
    assert "sourceOfTruth: \"capability-bundle-v1\"" in api
    assert "capabilityBundle?: CapabilityBundleSummary" in api
    assert "capabilityId?: string" in api
    assert "CapabilityGraphSemanticNode" in api
    assert "GeneratedWorkflowToolRecommendations" in builder_ui
    assert "outputCandidates={outputCandidates}" in builder_ui
    assert "onAddTool={onAddRecommendedTool || builder.addStep}" in builder_ui
    assert "onAddRecommendedTool?: (toolRevisionId: string) => void" in builder_ui
    assert "fetchWorkflowToolRecommendations" in recommendations_ui
    assert "createToolPrepareJob" in recommendations_ui
    assert "useToolPrepareTasks" in recommendations_ui
    assert "trackToolPrepareJob" in recommendations_ui
    assert "handlePrepareRecommendation" in recommendations_ui
    assert "recommendation.preparePayload" in recommendations_ui
    assert "useEffect" in recommendations_ui
    assert "selectedOutputCandidate" in recommendations_ui
    assert "matchingWorkflowReadyTool" in recommendations_ui
    assert "executionGate" in api
    assert "requiredState?: string" in api
    assert "canAddStep?: boolean" in api
    assert "sourceOfTruth?: string" in api
    assert "validationPlan?: WorkflowToolRecommendationValidationPlan" in api
    assert "latestPrepareJob?: WorkflowToolRecommendationLatestPrepareJob" in api
    assert "export type WorkflowToolRecommendationLatestPrepareJob" in api
    assert "validationResultId?: string" in _type_body(api, "WorkflowToolRecommendationLatestPrepareJob")
    assert "evidenceId?: string" in _type_body(api, "WorkflowToolRecommendationLatestPrepareJob")
    assert "toolRevisionId?: string" in api
    assert "toolId?: string" in api
    assert "WorkflowToolRecommendationPreparePayload" in api
    assert "preparePayload?: WorkflowToolRecommendationPreparePayload" in api
    assert "preparePayload?: WorkflowToolRecommendationPreparePayload" in _type_body(api, "WorkflowToolRecommendationCandidate")
    assert "ToolProfileWrapperEvidence" in api
    assert "snakemakeWrappers?: ToolProfileWrapperEvidence[]" in api
    assert "snakemakeWrapperCount?: number" in api
    assert "ruleSpecDraft?: RuleSpecDraft" in api
    assert "需验证到" in recommendations_ui
    assert "recommendation.executionGate.requiredState" in recommendations_ui
    assert "recommendation.executionGate?.sourceOfTruth" in recommendations_ui
    assert "recommendation.validationPlan?.stages?.length" in recommendations_ui
    assert "recommendation.latestPrepareJob?.status" in recommendations_ui
    assert "activePrepareJob" in recommendations_ui
    assert "recommendationAddStepRevisionId" in recommendations_ui
    assert "const addStepRevisionId = recommendationAddStepRevisionId(recommendation, tool)" in recommendations_ui
    assert "const canAddStep = Boolean(recommendation.executionGate?.canAddStep && addStepRevisionId)" in recommendations_ui
    assert "onAddTool(addStepRevisionId)" in recommendations_ui
    assert "recommendation.preparePayload || recommendation.candidate.preparePayload" in _function_body(
        recommendations_ui,
        "addedToolFromRecommendation",
    )
    assert "!canAddStep && !tool && recommendation.executionGate?.requiredState" in recommendations_ui
    assert "recommendation.executionGate?.toolRevisionId" in recommendations_ui
    assert "recommendation.executionGate?.toolId" in recommendations_ui
    assert "准备并验证工具" in recommendations_ui
    assert "先加入工具库" not in recommendations_ui
    assert "builder.addStep" not in recommendations_ui
    assert "recommendationCandidateName(recommendation)" in _function_body(recommendations_ui, "recommendationLabel")
    assert "recommendationCandidateName(recommendation)" in _function_body(recommendations_ui, "recommendationSearchQuery")
    candidate_name_body = _function_body(recommendations_ui, "recommendationCandidateName")
    assert "recommendation.candidate.toolNames?.[0]" in candidate_name_body
    assert "recommendation.candidate.profileId" in candidate_name_body
    assert "recommendation.candidate.candidateId" in candidate_name_body
    assert "recommendation.candidate.profileId" in candidate_name_body
    assert "recommendation.candidate.candidateId" in candidate_name_body


def test_generated_workflow_builder_has_explicit_dag_contract() -> None:
    model_path = COMPONENTS / "generated-workflow-model.ts"
    design_model_path = COMPONENTS / "workflow-design-draft-model.ts"
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
    assert design_model_path.exists()
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
    design_model = design_model_path.read_text(encoding="utf-8")
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
    assert "export type GeneratedWorkflowInputBinding" in model
    assert "fromUpload" in model
    assert "fromUpload" not in design_model.split("export function buildWorkflowDesignDraft", 1)[0]
    assert "fromInput" in design_model
    assert "fromStep" in model
    assert "GeneratedWorkflowExposedOutput" in model
    assert "buildWorkflowDesignDraft" in design_model
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
    assert "workflowDesignDraftToGraphDraft" in design_model
    assert "audit?: RulePortEdgeAudit" in model
    assert "audit: edge.audit" in model
    assert "audit: binding.audit" in model
    assert "contractVersion:" in design_model
    assert "nodes: graphDraft.nodes.map" in design_model
    assert "edges: graphDraft.edges.map" in design_model
    assert "audit: workflowDesignEdgeAuditForDraft(edge.audit)" in design_model
    assert "function workflowDesignEdgeAuditForDraft" in design_model
    assert "hardChecks: JSON.stringify(audit.hardChecks)" in design_model
    assert "evidence: JSON.stringify(audit.evidence)" in design_model
    assert "WORKFLOW_DESIGN_EDGE_AUDIT_KEYS" in design_model
    assert "workflowDesignValidateScalarRecord" in design_model
    assert "Object.entries(audit).find" in design_model
    assert "!WORKFLOW_DESIGN_EDGE_AUDIT_KEYS.has(key)" in design_model
    assert "function workflowDesignAuditStringArray" in design_model
    assert "JSON.parse(value)" in design_model
    assert "if (audit === undefined) return undefined" in design_model
    assert 'typeof audit !== "object" || Array.isArray(audit)' in design_model
    assert "outputs: graphDraft.outputs.map" in design_model
    assert "runtime: workflowDesignRuntimeForDraft(node.runtime)" in design_model
    assert "function workflowDesignRuntimeForDraft" in design_model
    assert "resources: { ...(runtime.resources || {}) }" in design_model
    assert "schedulerResources: { ...(runtime.schedulerResources || {}) }" in design_model
    assert "WORKFLOW_DESIGN_NODE_INPUT_EDGE_UNSUPPORTED" in design_model
    assert "WORKFLOW_DESIGN_INPUT_ROLE_UNKNOWN" in design_model
    assert '"fromInput" in binding' not in design_model
    assert "existingDraft?: WorkflowDesignDraft" in design_model
    assert "description: existingDraft?.metadata.description" in design_model
    assert "tags: existingDraft?.metadata.tags" in design_model
    assert "item.id === node.id && item.toolRevisionId === node.toolRevisionId" in design_model
    assert "existingNodeOutputEntries" in design_model
    assert "exposedOutputNames.has(outputName)" in design_model
    assert "metadata: existingNode?.metadata || {}" in design_model
    assert "provenance: existingNode?.provenance || { source: \"workflow-builder\" }" in design_model
    assert "metadata: existingOutput?.metadata || {}" in design_model
    assert "provenance: existingDraft?.provenance || { createdBy: \"workflow-builder\" }" in design_model
    assert "return binding as WorkflowDesignInputBinding" not in design_model
    assert "ruleSpecDraft: readToolRuleSpecDraft(tool)" not in model
    assert "resourceBindings" in design_model
    assert "databases" not in model
    assert "WORKFLOW_STEP_PARAM_REQUIRED" in param_contract
    assert "commandParamNames" in param_contract
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
    assert "inputCount={state.generatedInputCount}" in detail_page
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
    assert "OutputExposureEditor" in builder_ui
    assert "script:" in builder_ui
    assert "module:" in builder_ui

    assert "buildGeneratedRunSpec" not in page_model
    assert "submitWorkflowDesignRun" in api
    assert "compileWorkflowDesignDraft" in api
    assert "/compile" in api
    assert "WorkflowDesignCompileResult" in api
    assert "workflowRevisionId?: string" in design_model
    assert "export type WorkflowRevisionSummary" in design_model
    assert "WorkflowRevision" in builder_ui
    assert "result.workflowRevisionId" in builder_ui
    assert "workflowRevisionId: string" in api
    assert "WORKFLOW_REVISION_ID_REQUIRED" in api
    assert "workflowRevisionId: normalizedWorkflowRevisionId" in api
    assert "currentWorkflowDesignCompileResult?.workflowRevisionId" in page_hook
    assert "workflowDesignDraftsCacheKey(options.serverId)" in api
    assert "requireWorkflowDesignPlannedInputs" in api
    assert "role: plannedInputs[index].role" in api
    assert "filename: plannedInputs[index].filename" in api
    upload_file_body = _function_body(api, "uploadWorkflowFile")
    workflow_submit_body = _function_body(api, "submitWorkflowDesignRun")
    pipeline_submit_body = _function_body(api, "submitPipelineWorkflowRun")
    assert workflow_submit_body.index("const plannedInputs = requireWorkflowDesignPlannedInputs(plannedRunSpec)") < workflow_submit_body.index("uploadWorkflowFile(file, server.serverId)")
    assert workflow_submit_body.index("plannedInputs.length !== files.length") < workflow_submit_body.index("uploadWorkflowFile(file, server.serverId)")
    assert "plannedInputs.length !== uploads.length" not in workflow_submit_body
    assert "filename: upload.filename" not in workflow_submit_body
    assert 'typeof roleValue !== "string"' in api
    assert 'typeof filenameValue !== "string"' in api
    assert "serverId?: string" in api
    assert "serverId ? { serverId } : {}" in upload_file_body
    assert "uploadWorkflowFile(file, server.serverId)" in workflow_submit_body
    assert "uploadWorkflowFile(file, server.serverId)" in pipeline_submit_body
    assert "WORKFLOW_DESIGN_RUN_INPUTS_MISMATCH" in api
    assert "WorkflowDesignPlan" in api
    assert "WORKFLOW_DESIGN_PLAN_RUN_SPEC_REQUIRED" in api
    assert "workflowDesign.draftId" in api
    assert "workflowDesign.revision" in api
    assert "useGeneratedWorkflowBuilder" in page_hook
    assert "addRecommendedWorkflowTool" in page_hook
    assert "fetchWorkflowTools({ forceRefresh: true })" in page_hook
    assert "generatedBuilder.addStep(toolRevisionId)" in page_hook
    assert "setTools(nextTools)" in page_hook
    assert "buildWorkflowDesignDraft" in page_hook
    assert "existingDraft: activeWorkflowDesignDraft?.draft" in page_hook
    assert "saveAndValidateGeneratedWorkflowDesign" in page_hook
    assert "currentWorkflowDesignPlan?.valid === true" in page_hook
    assert "currentWorkflowDesignPlan ? workflowDesignCompileResult : null" in page_hook
    assert "workflowDesignCompileResult: currentWorkflowDesignCompileResult" in page_hook
    assert "currentWorkflowDesignDraftError" in page_hook
    assert "workflowErrorMessage(err, \"WORKFLOW_DESIGN_DRAFT_INVALID\")" in page_hook
    assert "workflowDesignError: currentWorkflowDesignDraftError || workflowDesignError" in page_hook
    assert "catch {\n      return null;" not in page_hook
    assert "workflowDesignPlanSignature !== currentWorkflowDesignSignature" in page_hook
    assert "stableWorkflowDesignStringify(draft)" in page_hook
    assert "function stableWorkflowDesignStringify" in page_hook
    assert "Object.keys(value).sort()" in page_hook
    assert "return JSON.stringify(draft)" not in page_hook
    assert "setWorkflowDesignPlanSignature(\"\")" in page_hook
    assert "const plan = currentWorkflowDesignPlan" in page_hook
    assert "const plan = await saveAndValidateGeneratedWorkflowDesign()" not in page_hook
    assert "compileGeneratedWorkflowDesign" in page_hook
    assert "workflowDesignCompileResult" in page_hook
    assert "fetchWorkflowDesignDrafts({ ...options, serverId })" in page_hook
    assert 'serverResult.status === "rejected"' in page_hook
    assert "读取工作流运行服务失败" in page_hook
    assert 'serverResult.status === "fulfilled" ? serverResult.value.serverId : ""' not in page_hook
    assert "catch {\n        setWorkflowDesignDrafts([])" not in page_hook
    assert "WORKFLOW_DESIGN_DRAFT_NOT_FOUND: ${draftId}" in page_hook
    assert "throw new Error(message)" in page_hook
    assert "编译导出" in builder_ui
    assert "WorkflowDesignCompileSummary" in builder_ui
    assert "GeneratedWorkflowBuilder" in detail_page
    assert "onAddRecommendedTool={state.addRecommendedWorkflowTool}" in detail_page
    assert "onCompile" in detail_page
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
