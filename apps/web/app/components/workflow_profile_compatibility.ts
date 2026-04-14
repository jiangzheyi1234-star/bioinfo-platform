"use client";

import type { WorkflowCompatibilitySummary } from "./detection_workspace_types";

export function emptyWorkflowCompatibilitySummary(): WorkflowCompatibilitySummary {
  return {
    task_id: "",
    workflow_snapshot_id: "",
    workflow_id: "",
    compatible: false,
    reasons: [],
    preflight: null,
    recommended_profile: "",
    recommended_profile_details: null,
    supported_profile_kinds: [],
    runtime_capabilities: null,
    server_profiles: [],
    workflow_profiles: [],
    selected_profile: null,
    selection_reason: "",
  };
}

export function summarizeWorkflowCompatibility(summary: WorkflowCompatibilitySummary, compatibilityError: string): string {
  if (compatibilityError) {
    return `兼容性检查失败：${compatibilityError}`;
  }
  if (!summary.server_profiles.length) {
    return "保存 workflow 后即可获取兼容性与推荐 profile。";
  }
  const serverAvailable = summary.server_profiles.filter((item) => item.available_on_server).length;
  const workflowAvailable = summary.workflow_profiles.filter((item) => item.compatible_with_workflow).length;
  const selected = summary.selected_profile?.profile_id || "未选定";
  return `服务器可用 ${serverAvailable} 项 · 当前 workflow 可用 ${workflowAvailable} 项 · 选定 ${selected}`;
}
