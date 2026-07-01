"use client";

import { useEffect, useMemo, useReducer } from "react";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  buildConverterInsertionPatch,
  type RulePortConverterInsertionRequest,
} from "./generated-workflow-converter-recommendation";
import {
  commitWorkflowEditorHistory,
  createWorkflowEditorHistory,
  redoWorkflowEditorHistory,
  replaceWorkflowEditorHistory,
  undoWorkflowEditorHistory,
  type WorkflowEditorHistory,
} from "./generated-workflow-history";
import {
  createGeneratedWorkflowGraphDraft,
  createStepDraft,
  createStepParams,
  findCompatibleOutputBinding,
  generatedWorkflowDraftToGraphDraft,
  graphNodePosition,
  graphNodeMetadataWithPosition,
  graphNodeMetadataWithSubflow,
  graphDraftToGeneratedWorkflowDraft,
  readRuleInputs,
  readRuleOutputs,
  portsCompatible,
  validateGeneratedWorkflowDraft,
  workflowToolRevisionEntries,
  workflowToolRevisionId,
  type GeneratedWorkflowDraft,
  type GeneratedWorkflowExposedOutput,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowInputBinding,
  type GeneratedWorkflowParamValue,
  type GeneratedWorkflowStepRuntime,
} from "./generated-workflow-model";
import {
  databaseMatchesWorkflowResource,
  generatedToolResourceEntries,
  type WorkflowResourceBindings,
} from "./workflows-page-model";
import { autoEdgeAudit, explainPortRecommendation, manualEdgeAudit } from "./generated-workflow-recommendation-contract";
import { autoBindGeneratedWorkflowResources } from "./generated-workflow-resource-binding";

type GraphNodePosition = { x: number; y: number };
export type GeneratedWorkflowPreferredSourceOutput = {
  output: string;
  stepId: string;
  targetInput?: string;
};
export type GeneratedWorkflowAddStepOptions = {
  position?: GraphNodePosition;
  preferredSourceOutput?: GeneratedWorkflowPreferredSourceOutput;
};

type BuilderAction =
  | { type: "reset_tools"; tools: AddedTool[] }
  | { type: "load_graph_draft"; draft: GeneratedWorkflowGraphDraft }
  | { type: "load_resource_bindings"; selectedResourceIds: Record<string, string> }
  | { type: "redo_graph" }
  | { type: "undo_graph" }
  | {
      type: "add_step";
      position?: GraphNodePosition;
      preferredSourceOutput?: GeneratedWorkflowPreferredSourceOutput;
      tool: AddedTool;
      tools: AddedTool[];
    }
  | { type: "insert_converter"; converterTool: AddedTool; request: RulePortConverterInsertionRequest }
  | { type: "remove_step"; stepId: string }
  | { type: "set_step_id"; stepId: string; nextId: string }
  | { type: "set_step_tool"; stepId: string; tool: AddedTool; tools: AddedTool[] }
  | { type: "set_node_subflow"; stepId: string; label: string }
  | { type: "set_node_position"; stepId: string; position: GraphNodePosition }
  | { type: "set_node_positions"; positions: Record<string, GraphNodePosition> }
  | { type: "set_input"; stepId: string; inputName: string; binding: GeneratedWorkflowInputBinding }
  | { type: "set_step_param"; stepId: string; paramName: string; value: GeneratedWorkflowParamValue }
  | { type: "set_step_runtime"; stepId: string; runtime: GeneratedWorkflowStepRuntime }
  | { type: "add_output"; output: GeneratedWorkflowExposedOutput }
  | { type: "remove_output"; index: number }
  | { type: "set_output"; index: number; output: GeneratedWorkflowExposedOutput }
  | { type: "set_resource"; resourceKey: string; resourceId: string };

type BuilderState = {
  graphHistory: WorkflowEditorHistory<GeneratedWorkflowGraphDraft>;
  selectedResourceIds: Record<string, string>;
};

export function useGeneratedWorkflowBuilder(tools: AddedTool[], availableResources: DatabaseItem[], inputCount = 0) {
  const [state, dispatch] = useReducer(builderReducer, {
    graphHistory: createWorkflowEditorHistory(createGeneratedWorkflowGraphDraft(tools)),
    selectedResourceIds: {},
  });

  useEffect(() => {
    dispatch({ type: "reset_tools", tools });
  }, [tools]);

  const toolByRevisionId = useMemo(() => new Map(workflowToolRevisionEntries(tools)), [tools]);
  const graphDraft = state.graphHistory.present;
  const draft = useMemo(() => graphDraftToGeneratedWorkflowDraft(graphDraft), [graphDraft]);
  const selectedTools = useMemo(
    () => draft.steps.map((step) => toolByRevisionId.get(step.toolRevisionId)).filter((tool): tool is AddedTool => Boolean(tool)),
    [draft.steps, toolByRevisionId]
  );
  const resourceEntries = useMemo(
    () => generatedToolResourceEntries(selectedTools),
    [selectedTools]
  );
  useEffect(() => {
    const selectedResourceIds = autoBindGeneratedWorkflowResources(resourceEntries, availableResources, state.selectedResourceIds);
    if (selectedResourceIds !== state.selectedResourceIds) {
      dispatch({ type: "load_resource_bindings", selectedResourceIds });
    }
  }, [availableResources, resourceEntries, state.selectedResourceIds]);
  const selectedResources = useMemo(
    () => availableResources.filter((resource) => Object.values(state.selectedResourceIds).includes(resource.id)),
    [availableResources, state.selectedResourceIds]
  );
  const resourceBindings = useMemo<WorkflowResourceBindings>(
    () => Object.fromEntries(
      resourceEntries
        .map(([key, spec]) => {
          const resourceId = state.selectedResourceIds[key];
          const resource = availableResources.find((item) => item.id === resourceId);
          return resource && databaseMatchesWorkflowResource(resource, spec) ? [key, { databaseId: resource.id }] : null;
        })
        .filter((entry): entry is [string, { databaseId: string }] => Boolean(entry))
    ),
    [availableResources, resourceEntries, state.selectedResourceIds]
  );
  const validation = useMemo(() => {
    const base = validateGeneratedWorkflowDraft(graphDraft, tools, { inputCount });
    const resourceErrors = resourceEntries
      .filter(([key, spec]) => spec.required && !resourceBindings[key])
      .map(([key]) => ({
        code: "WORKFLOW_RESOURCE_BINDING_REQUIRED",
        message: `缺少必选数据库资源 ${key}`,
      }));
    return { ...base, errors: [...base.errors, ...resourceErrors] };
  }, [graphDraft, inputCount, resourceBindings, resourceEntries, tools]);

  return {
    draft,
    graphDraft,
    canRedo: state.graphHistory.future.length > 0,
    canUndo: state.graphHistory.past.length > 0,
    validation,
    resourceEntries,
    selectedResourceIds: Object.values(state.selectedResourceIds).filter(Boolean),
    selectedResourceDatabaseIds: state.selectedResourceIds,
    selectedToolIds: draft.steps.map((step) => step.toolRevisionId),
    selectedTools,
    selectedResources,
    resourceBindings,
    loadGraphDraft: (draft: GeneratedWorkflowGraphDraft) => dispatch({ type: "load_graph_draft", draft }),
    loadResourceBindings: (selectedResourceIds: Record<string, string>) =>
      dispatch({ type: "load_resource_bindings", selectedResourceIds }),
    addStep: (toolRevisionId: string, options: GeneratedWorkflowAddStepOptions = {}) => {
      const tool = toolByRevisionId.get(toolRevisionId);
      if (tool) {
        dispatch({
          type: "add_step",
          position: options.position,
          preferredSourceOutput: options.preferredSourceOutput,
          tool,
          tools,
        });
      }
    },
    insertConverter: (request: RulePortConverterInsertionRequest) => {
      const converterTool = toolByRevisionId.get(request.converter.converterToolRevisionId);
      if (!converterTool) {
        throw new Error("WORKFLOW_CONVERTER_INSERTION_TOOL_UNAVAILABLE");
      }
      dispatch({ type: "insert_converter", converterTool, request });
    },
    removeStep: (stepId: string) => dispatch({ type: "remove_step", stepId }),
    redo: () => dispatch({ type: "redo_graph" }),
    setStepId: (stepId: string, nextId: string) => dispatch({ type: "set_step_id", stepId, nextId }),
    setStepTool: (stepId: string, toolRevisionId: string) => {
      const tool = toolByRevisionId.get(toolRevisionId);
      if (tool) dispatch({ type: "set_step_tool", stepId, tool, tools });
    },
    setNodeSubflow: (stepId: string, label: string) => dispatch({ type: "set_node_subflow", stepId, label }),
    setNodePosition: (stepId: string, position: GraphNodePosition) =>
      dispatch({ type: "set_node_position", stepId, position }),
    setNodePositions: (positions: Record<string, GraphNodePosition>) =>
      dispatch({ type: "set_node_positions", positions }),
    setInputBinding: (stepId: string, inputName: string, binding: GeneratedWorkflowInputBinding) =>
      dispatch({ type: "set_input", stepId, inputName, binding }),
    setStepParam: (stepId: string, paramName: string, value: GeneratedWorkflowParamValue) =>
      dispatch({ type: "set_step_param", stepId, paramName, value }),
    setStepRuntime: (stepId: string, runtime: GeneratedWorkflowStepRuntime) =>
      dispatch({ type: "set_step_runtime", stepId, runtime }),
    addExposedOutput: (output: GeneratedWorkflowExposedOutput) => dispatch({ type: "add_output", output }),
    removeExposedOutput: (index: number) => dispatch({ type: "remove_output", index }),
    setExposedOutput: (index: number, output: GeneratedWorkflowExposedOutput) => dispatch({ type: "set_output", index, output }),
    setResourceBinding: (resourceKey: string, resourceId: string) => dispatch({ type: "set_resource", resourceKey, resourceId }),
    undo: () => dispatch({ type: "undo_graph" }),
  };
}

export type GeneratedWorkflowBuilderController = ReturnType<typeof useGeneratedWorkflowBuilder>;

function builderReducer(state: BuilderState, action: BuilderAction): BuilderState {
  if (action.type === "reset_tools") {
    const availableIds = new Set(action.tools.map((tool) => workflowToolRevisionId(tool)).filter(Boolean));
    if (
      state.graphHistory.present.nodes.length > 0
      && graphHistoryToolsAvailable(state.graphHistory, availableIds)
    ) {
      return state;
    }
    if (graphToolsAvailable(state.graphHistory.present, availableIds)) {
      return { ...state, graphHistory: replaceWorkflowEditorHistory(state.graphHistory, state.graphHistory.present) };
    }
    return { ...state, graphHistory: replaceWorkflowEditorHistory(state.graphHistory, createGeneratedWorkflowGraphDraft(action.tools)) };
  }
  if (action.type === "load_graph_draft") {
    return { ...state, graphHistory: replaceWorkflowEditorHistory(state.graphHistory, action.draft) };
  }
  if (action.type === "load_resource_bindings") {
    return { ...state, selectedResourceIds: action.selectedResourceIds };
  }
  if (action.type === "undo_graph") {
    return { ...state, graphHistory: undoWorkflowEditorHistory(state.graphHistory) };
  }
  if (action.type === "redo_graph") {
    return { ...state, graphHistory: redoWorkflowEditorHistory(state.graphHistory) };
  }
  if (action.type === "add_step") {
    const draft = graphDraftToGeneratedWorkflowDraft(state.graphHistory.present);
    const nextStep = applyPreferredSourceOutputBinding({
      preferredSourceOutput: action.preferredSourceOutput,
      step: createStepDraft(action.tool, draft.steps.map((step) => step.id), draft.steps, action.tools),
      tools: action.tools,
      upstreamSteps: draft.steps,
    });
    const positionedStep = action.position
      ? { ...nextStep, metadata: graphNodeMetadataWithPosition(nextStep.metadata, action.position) }
      : nextStep;
    return updateStepDraft(state, (current) => ({ ...current, steps: [...current.steps, positionedStep] }));
  }
  if (action.type === "insert_converter") {
    return commitGraphDraft(state, buildConverterInsertionPatch({
        converterTool: action.converterTool,
        graphDraft: state.graphHistory.present,
        request: action.request,
      }));
  }
  if (action.type === "remove_step") {
    return updateStepDraft(state, (draft) => ({
      steps: draft.steps
          .filter((step) => step.id !== action.stepId)
          .map((step) => ({
            ...step,
            inputs: Object.fromEntries(
              Object.entries(step.inputs).map(([name, binding]) => [
                name,
                isRemovedStepBinding(binding, action.stepId) ? "" : binding,
              ])
            ),
          })),
      outputs: draft.outputs.filter((output) => output.fromStep !== action.stepId),
    }));
  }
  if (action.type === "set_step_id") {
    return renameStep(state, action.stepId, action.nextId);
  }
  if (action.type === "set_step_tool") {
    return setStepTool(state, action.stepId, action.tool, action.tools);
  }
  if (action.type === "set_node_subflow") {
    return commitGraphDraftIfChanged(
      state,
      graphDraftWithNodeSubflow(state.graphHistory.present, action.stepId, action.label)
    );
  }
  if (action.type === "set_node_position") {
    return commitGraphDraftIfChanged(
      state,
      graphDraftWithNodePosition(state.graphHistory.present, action.stepId, action.position)
    );
  }
  if (action.type === "set_node_positions") {
    return commitGraphDraftIfChanged(
      state,
      graphDraftWithNodePositions(state.graphHistory.present, action.positions)
    );
  }
  if (action.type === "set_input") {
    const binding =
      action.binding && typeof action.binding === "object" && "fromStep" in action.binding && "output" in action.binding && !action.binding.audit
        ? { ...action.binding, audit: manualEdgeAudit() }
        : action.binding;
    return updateStepDraft(state, (draft) => ({
      ...draft,
      steps: draft.steps.map((step) =>
          step.id === action.stepId ? { ...step, inputs: { ...step.inputs, [action.inputName]: binding } } : step
      ),
    }));
  }
  if (action.type === "set_step_param") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      steps: draft.steps.map((step) =>
          step.id === action.stepId
            ? { ...step, params: { ...(step.params || {}), [action.paramName]: action.value } }
            : step
      ),
    }));
  }
  if (action.type === "set_step_runtime") {
    return {
      ...state,
      graphHistory: commitWorkflowEditorHistory(state.graphHistory, {
        ...state.graphHistory.present,
        nodes: state.graphHistory.present.nodes.map((node) =>
          node.id === action.stepId ? { ...node, runtime: action.runtime } : node
        ),
      }),
    };
  }
  if (action.type === "add_output") {
    return updateStepDraft(state, (draft) => ({ ...draft, outputs: [...draft.outputs, action.output] }));
  }
  if (action.type === "remove_output") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      outputs: draft.outputs.filter((_, index) => index !== action.index),
    }));
  }
  if (action.type === "set_output") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      outputs: draft.outputs.map((output, index) => index === action.index ? action.output : output),
    }));
  }
  if (action.type === "set_resource") {
    const selectedResourceIds = { ...state.selectedResourceIds };
    if (action.resourceId) {
      selectedResourceIds[action.resourceKey] = action.resourceId;
    } else {
      delete selectedResourceIds[action.resourceKey];
    }
    return { ...state, selectedResourceIds };
  }
  return state;
}

function renameStep(state: BuilderState, stepId: string, nextId: string): BuilderState {
  const trimmed = nextId.trim();
  if (!trimmed) return state;
  return updateStepDraft(state, (draft) => ({
      steps: draft.steps.map((step) => {
        const inputs = Object.fromEntries(
          Object.entries(step.inputs).map(([name, binding]) => [
            name,
            isRemovedStepBinding(binding, stepId) ? { fromStep: trimmed, output: binding.output, audit: binding.audit } : binding,
          ])
        );
        return step.id === stepId ? { ...step, id: trimmed, inputs } : { ...step, inputs };
      }),
      outputs: draft.outputs.map((output) =>
        output.fromStep === stepId ? { ...output, fromStep: trimmed } : output
      ),
  }));
}

function setStepTool(state: BuilderState, stepId: string, tool: AddedTool, tools: AddedTool[]): BuilderState {
  const draft = graphDraftToGeneratedWorkflowDraft(state.graphHistory.present);
  const stepIndex = draft.steps.findIndex((step) => step.id === stepId);
  const upstreamSteps = stepIndex >= 0 ? draft.steps.slice(0, stepIndex) : [];
  const inputs: Record<string, GeneratedWorkflowInputBinding> = Object.fromEntries(
    readRuleInputs(tool).map((input) => [
      input.name,
      findCompatibleOutputBinding(input, upstreamSteps, tools) || "",
    ])
  );
  const outputNames = new Set(readRuleOutputs(tool).map((output) => output.name));
  const params = createStepParams(tool);
  return updateStepDraft(state, (current) => ({
    steps: current.steps.map((step) => step.id === stepId ? { ...step, toolRevisionId: workflowToolRevisionId(tool), inputs, params } : step),
    outputs: current.outputs.filter((output) => output.fromStep !== stepId || outputNames.has(output.output)),
  }));
}

function applyPreferredSourceOutputBinding({
  preferredSourceOutput,
  step,
  tools,
  upstreamSteps,
}: {
  preferredSourceOutput: GeneratedWorkflowPreferredSourceOutput | undefined;
  step: GeneratedWorkflowDraft["steps"][number];
  tools: AddedTool[];
  upstreamSteps: GeneratedWorkflowDraft["steps"];
}): GeneratedWorkflowDraft["steps"][number] {
  if (!preferredSourceOutput) return step;
  const toolByRevisionId = new Map(workflowToolRevisionEntries(tools));
  const sourceStep = upstreamSteps.find((candidate) => candidate.id === preferredSourceOutput.stepId);
  const sourceOutput = readRuleOutputs(toolByRevisionId.get(sourceStep?.toolRevisionId || ""))
    .find((output) => output.name === preferredSourceOutput.output);
  if (!sourceOutput) return step;

  const targetInputs = readRuleInputs(toolByRevisionId.get(step.toolRevisionId))
    .filter((input) => !preferredSourceOutput.targetInput || input.name === preferredSourceOutput.targetInput);
  const targetInput = targetInputs.find((input) => portsCompatible(input, sourceOutput));
  if (!targetInput) return step;

  return {
    ...step,
    inputs: {
      ...step.inputs,
      [targetInput.name]: {
        fromStep: preferredSourceOutput.stepId,
        output: preferredSourceOutput.output,
        audit: autoEdgeAudit(explainPortRecommendation(targetInput, sourceOutput)),
      },
    },
  };
}

function updateStepDraft(state: BuilderState, update: (draft: GeneratedWorkflowDraft) => GeneratedWorkflowDraft): BuilderState {
  return commitGraphDraft(
    state,
    generatedWorkflowDraftToGraphDraft(update(graphDraftToGeneratedWorkflowDraft(state.graphHistory.present)))
  );
}

function commitGraphDraft(state: BuilderState, graphDraft: GeneratedWorkflowGraphDraft): BuilderState {
  return {
    ...state,
    graphHistory: commitWorkflowEditorHistory(state.graphHistory, graphDraft),
  };
}

function commitGraphDraftIfChanged(state: BuilderState, graphDraft: GeneratedWorkflowGraphDraft): BuilderState {
  return graphDraft === state.graphHistory.present ? state : commitGraphDraft(state, graphDraft);
}

function graphDraftWithNodePosition(
  draft: GeneratedWorkflowGraphDraft,
  stepId: string,
  position: GraphNodePosition
): GeneratedWorkflowGraphDraft {
  let changed = false;
  const nodes = draft.nodes.map((node) => {
    if (node.id !== stepId) return node;
    if (graphNodePositionMatches(node.metadata, position)) return node;
    changed = true;
    return { ...node, metadata: graphNodeMetadataWithPosition(node.metadata, position) };
  });
  return changed ? { ...draft, nodes } : draft;
}

function graphDraftWithNodePositions(
  draft: GeneratedWorkflowGraphDraft,
  positions: Record<string, GraphNodePosition>
): GeneratedWorkflowGraphDraft {
  let changed = false;
  const nodes = draft.nodes.map((node) => {
    const position = positions[node.id];
    if (!position || graphNodePositionMatches(node.metadata, position)) return node;
    changed = true;
    return { ...node, metadata: graphNodeMetadataWithPosition(node.metadata, position) };
  });
  return changed ? { ...draft, nodes } : draft;
}

function graphDraftWithNodeSubflow(
  draft: GeneratedWorkflowGraphDraft,
  stepId: string,
  label: string
): GeneratedWorkflowGraphDraft {
  let changed = false;
  const nodes = draft.nodes.map((node) => {
    if (node.id !== stepId) return node;
    const metadata = graphNodeMetadataWithSubflow(node.metadata, label);
    if (graphNodeMetadataMatches(node.metadata, metadata)) return node;
    changed = true;
    return { ...node, metadata };
  });
  return changed ? { ...draft, nodes } : draft;
}

function graphNodePositionMatches(
  metadata: GeneratedWorkflowGraphDraft["nodes"][number]["metadata"] | undefined,
  position: GraphNodePosition
) {
  const currentPosition = graphNodePosition({ metadata });
  const nextPosition = graphNodePosition({ metadata: graphNodeMetadataWithPosition(metadata, position) });
  return Boolean(
    currentPosition
    && nextPosition
    && currentPosition.x === nextPosition.x
    && currentPosition.y === nextPosition.y
  );
}

function graphNodeMetadataMatches(
  left: GeneratedWorkflowGraphDraft["nodes"][number]["metadata"] | undefined,
  right: GeneratedWorkflowGraphDraft["nodes"][number]["metadata"] | undefined
) {
  const leftEntries = Object.entries(left || {});
  const rightEntries = Object.entries(right || {});
  if (leftEntries.length !== rightEntries.length) return false;
  return leftEntries.every(([key, value]) => right?.[key] === value);
}

function graphHistoryToolsAvailable(
  history: WorkflowEditorHistory<GeneratedWorkflowGraphDraft>,
  availableIds: Set<string>
) {
  return [history.present, ...history.past, ...history.future].every((draft) => graphToolsAvailable(draft, availableIds));
}

function graphToolsAvailable(draft: GeneratedWorkflowGraphDraft, availableIds: Set<string>) {
  return draft.nodes.length > 0 && draft.nodes.every((node) => availableIds.has(node.toolRevisionId));
}

function isRemovedStepBinding(
  binding: GeneratedWorkflowInputBinding,
  stepId: string
): binding is { fromStep: string; output: string } {
  return Boolean(binding && typeof binding === "object" && "fromStep" in binding && binding.fromStep === stepId);
}
