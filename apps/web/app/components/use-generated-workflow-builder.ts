"use client";

import { useEffect, useMemo, useReducer } from "react";

import type { DatabaseItem } from "./database-page-model";
import type { AddedTool } from "./tools-page-model";
import {
  createGeneratedWorkflowGraphDraft,
  createStepDraft,
  createStepParams,
  findCompatibleOutputBinding,
  generatedWorkflowDraftToGraphDraft,
  graphDraftToGeneratedWorkflowDraft,
  readRuleInputs,
  readRuleOutputs,
  validateGeneratedWorkflowDraft,
  type GeneratedWorkflowDraft,
  type GeneratedWorkflowExposedOutput,
  type GeneratedWorkflowGraphDraft,
  type GeneratedWorkflowInputBinding,
  type GeneratedWorkflowParamValue,
} from "./generated-workflow-model";
import {
  databaseMatchesWorkflowResource,
  generatedToolResourceEntries,
  type WorkflowResourceBindings,
} from "./workflows-page-model";

type BuilderAction =
  | { type: "reset_tools"; tools: AddedTool[] }
  | { type: "add_step"; tool: AddedTool; tools: AddedTool[] }
  | { type: "remove_step"; stepId: string }
  | { type: "set_step_id"; stepId: string; nextId: string }
  | { type: "set_step_tool"; stepId: string; tool: AddedTool; tools: AddedTool[] }
  | { type: "set_input"; stepId: string; inputName: string; binding: GeneratedWorkflowInputBinding }
  | { type: "set_step_param"; stepId: string; paramName: string; value: GeneratedWorkflowParamValue }
  | { type: "add_output"; output: GeneratedWorkflowExposedOutput }
  | { type: "remove_output"; index: number }
  | { type: "set_output"; index: number; output: GeneratedWorkflowExposedOutput }
  | { type: "set_resource"; resourceKey: string; resourceId: string };

type BuilderState = {
  graphDraft: GeneratedWorkflowGraphDraft;
  selectedResourceIds: Record<string, string>;
};

export function useGeneratedWorkflowBuilder(tools: AddedTool[], availableResources: DatabaseItem[], inputCount = 0) {
  const [state, dispatch] = useReducer(builderReducer, {
    graphDraft: createGeneratedWorkflowGraphDraft(tools),
    selectedResourceIds: {},
  });

  useEffect(() => {
    dispatch({ type: "reset_tools", tools });
  }, [tools]);

  const toolById = useMemo(() => new Map(tools.map((tool) => [tool.id, tool])), [tools]);
  const draft = useMemo(() => graphDraftToGeneratedWorkflowDraft(state.graphDraft), [state.graphDraft]);
  const selectedTools = useMemo(
    () => draft.steps.map((step) => toolById.get(step.toolId)).filter((tool): tool is AddedTool => Boolean(tool)),
    [draft.steps, toolById]
  );
  const resourceEntries = useMemo(
    () => generatedToolResourceEntries(selectedTools),
    [selectedTools]
  );
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
    const base = validateGeneratedWorkflowDraft(state.graphDraft, tools, { inputCount });
    const resourceErrors = resourceEntries
      .filter(([key, spec]) => spec.required && !resourceBindings[key])
      .map(([key]) => ({
        code: "WORKFLOW_RESOURCE_BINDING_REQUIRED",
        message: `缺少必选数据库资源 ${key}`,
      }));
    return { ...base, errors: [...base.errors, ...resourceErrors] };
  }, [inputCount, resourceBindings, resourceEntries, state.graphDraft, tools]);

  return {
    draft,
    graphDraft: state.graphDraft,
    validation,
    resourceEntries,
    selectedResourceIds: Object.values(state.selectedResourceIds).filter(Boolean),
    selectedResourceDatabaseIds: state.selectedResourceIds,
    selectedToolIds: draft.steps.map((step) => step.toolId),
    selectedTools,
    selectedResources,
    resourceBindings,
    addStep: (toolId: string) => {
      const tool = toolById.get(toolId);
      if (tool) dispatch({ type: "add_step", tool, tools });
    },
    removeStep: (stepId: string) => dispatch({ type: "remove_step", stepId }),
    setStepId: (stepId: string, nextId: string) => dispatch({ type: "set_step_id", stepId, nextId }),
    setStepTool: (stepId: string, toolId: string) => {
      const tool = toolById.get(toolId);
      if (tool) dispatch({ type: "set_step_tool", stepId, tool, tools });
    },
    setInputBinding: (stepId: string, inputName: string, binding: GeneratedWorkflowInputBinding) =>
      dispatch({ type: "set_input", stepId, inputName, binding }),
    setStepParam: (stepId: string, paramName: string, value: GeneratedWorkflowParamValue) =>
      dispatch({ type: "set_step_param", stepId, paramName, value }),
    addExposedOutput: (output: GeneratedWorkflowExposedOutput) => dispatch({ type: "add_output", output }),
    removeExposedOutput: (index: number) => dispatch({ type: "remove_output", index }),
    setExposedOutput: (index: number, output: GeneratedWorkflowExposedOutput) => dispatch({ type: "set_output", index, output }),
    setResourceBinding: (resourceKey: string, resourceId: string) => dispatch({ type: "set_resource", resourceKey, resourceId }),
  };
}

export type GeneratedWorkflowBuilderController = ReturnType<typeof useGeneratedWorkflowBuilder>;

function builderReducer(state: BuilderState, action: BuilderAction): BuilderState {
  if (action.type === "reset_tools") {
    const availableIds = new Set(action.tools.map((tool) => tool.id));
    if (state.graphDraft.nodes.length > 0 && state.graphDraft.nodes.every((node) => availableIds.has(node.toolId))) {
      return state;
    }
    return { ...state, graphDraft: createGeneratedWorkflowGraphDraft(action.tools) };
  }
  if (action.type === "add_step") {
    const draft = graphDraftToGeneratedWorkflowDraft(state.graphDraft);
    const nextStep = createStepDraft(action.tool, draft.steps.map((step) => step.id), draft.steps, action.tools);
    return updateStepDraft(state, (current) => ({ ...current, steps: [...current.steps, nextStep] }));
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
      exposeOutputs: draft.exposeOutputs.filter((output) => output.fromStep !== action.stepId),
    }));
  }
  if (action.type === "set_step_id") {
    return renameStep(state, action.stepId, action.nextId);
  }
  if (action.type === "set_step_tool") {
    return setStepTool(state, action.stepId, action.tool, action.tools);
  }
  if (action.type === "set_input") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      steps: draft.steps.map((step) =>
          step.id === action.stepId ? { ...step, inputs: { ...step.inputs, [action.inputName]: action.binding } } : step
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
  if (action.type === "add_output") {
    return updateStepDraft(state, (draft) => ({ ...draft, exposeOutputs: [...draft.exposeOutputs, action.output] }));
  }
  if (action.type === "remove_output") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      exposeOutputs: draft.exposeOutputs.filter((_, index) => index !== action.index),
    }));
  }
  if (action.type === "set_output") {
    return updateStepDraft(state, (draft) => ({
      ...draft,
      exposeOutputs: draft.exposeOutputs.map((output, index) => index === action.index ? action.output : output),
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
            isRemovedStepBinding(binding, stepId) ? { fromStep: trimmed, output: binding.output } : binding,
          ])
        );
        return step.id === stepId ? { ...step, id: trimmed, inputs } : { ...step, inputs };
      }),
      exposeOutputs: draft.exposeOutputs.map((output) =>
        output.fromStep === stepId ? { ...output, fromStep: trimmed } : output
      ),
  }));
}

function setStepTool(state: BuilderState, stepId: string, tool: AddedTool, tools: AddedTool[]): BuilderState {
  const draft = graphDraftToGeneratedWorkflowDraft(state.graphDraft);
  const stepIndex = draft.steps.findIndex((step) => step.id === stepId);
  const upstreamSteps = stepIndex >= 0 ? draft.steps.slice(0, stepIndex) : [];
  const inputs = Object.fromEntries(
    readRuleInputs(tool).map((input) => [
      input.name,
      findCompatibleOutputBinding(input, upstreamSteps, tools) || "",
    ])
  );
  const outputNames = new Set(readRuleOutputs(tool).map((output) => output.name));
  const params = createStepParams(tool);
  return updateStepDraft(state, (current) => ({
    steps: current.steps.map((step) => step.id === stepId ? { ...step, toolId: tool.id, inputs, params } : step),
    exposeOutputs: current.exposeOutputs.filter((output) => output.fromStep !== stepId || outputNames.has(output.output)),
  }));
}

function updateStepDraft(state: BuilderState, update: (draft: GeneratedWorkflowDraft) => GeneratedWorkflowDraft): BuilderState {
  return {
    ...state,
    graphDraft: generatedWorkflowDraftToGraphDraft(update(graphDraftToGeneratedWorkflowDraft(state.graphDraft))),
  };
}

function isRemovedStepBinding(
  binding: GeneratedWorkflowInputBinding,
  stepId: string
): binding is { fromStep: string; output: string } {
  return Boolean(binding && typeof binding === "object" && "fromStep" in binding && binding.fromStep === stepId);
}
