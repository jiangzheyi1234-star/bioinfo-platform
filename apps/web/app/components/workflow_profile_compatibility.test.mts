import assert from "node:assert/strict";
import test from "node:test";

import { parseWorkflowCompatibilitySummary } from "./detection_workspace_utils.ts";
import { emptyWorkflowCompatibilitySummary, summarizeWorkflowCompatibility } from "./workflow_profile_compatibility.ts";

const payload = {
  task_id: "task_1",
  workflow_snapshot_id: "wsnap_1",
  workflow_id: "wf_1",
  compatible: true,
  reasons: [],
  preflight: {
    ok: true,
    arch: "x86_64",
    free_disk_gb: 42,
    recommended_profile: "personal_docker",
    recommended_profile_details: {
      profile_id: "personal_docker",
      server_id: "current",
      profile_kind: "personal_docker",
      executor: "local",
      packaging_mode: "container",
      container_runtime: "docker",
      work_dir: "~/.bioflow/runs/work",
      output_dir: "~/.bioflow/runs/output",
      cache_dir: "~/.bioflow/cache/containers",
    },
    supported_profile_kinds: ["personal_docker", "personal_conda"],
    runtime_capabilities: {
      java: { available: true, version: "21" },
      nextflow: { available: true, version: "24.10.0" },
      docker: { available: true },
      podman: { available: false },
      apptainer: { available: false },
      micromamba: { available: false },
      conda: { available: true },
      sbatch: { available: false },
    },
    checks: [],
    failures: [],
    warnings: [],
  },
  recommended_profile: "personal_docker",
  recommended_profile_details: {
    profile_id: "personal_docker",
    server_id: "current",
    profile_kind: "personal_docker",
    executor: "local",
    packaging_mode: "container",
    container_runtime: "docker",
    work_dir: "~/.bioflow/runs/work",
    output_dir: "~/.bioflow/runs/output",
    cache_dir: "~/.bioflow/cache/containers",
  },
  supported_profile_kinds: ["personal_docker", "personal_conda"],
  runtime_capabilities: {
    java: { available: true, version: "21" },
    nextflow: { available: true, version: "24.10.0" },
    docker: { available: true },
    podman: { available: false },
    apptainer: { available: false },
    micromamba: { available: false },
    conda: { available: true },
    sbatch: { available: false },
  },
  server_profiles: [
    {
      profile: {
        profile_id: "personal_docker",
        server_id: "current",
        profile_kind: "personal_docker",
        executor: "local",
        packaging_mode: "container",
        container_runtime: "docker",
        work_dir: "~/.bioflow/runs/work",
        output_dir: "~/.bioflow/runs/output",
        cache_dir: "~/.bioflow/cache/containers",
      },
      available_on_server: true,
      compatible_with_workflow: false,
      support_level: "Conda Only",
      incompatibility_reasons: ["personal_docker ❌ Unknown sample 缺少 runtime.container"],
    },
    {
      profile: {
        profile_id: "personal_conda",
        server_id: "current",
        profile_kind: "personal_conda",
        executor: "local",
        packaging_mode: "conda",
        container_runtime: "",
        work_dir: "~/.bioflow/runs/work",
        output_dir: "~/.bioflow/runs/output",
        cache_dir: "~/.bioflow/cache/conda",
      },
      available_on_server: true,
      compatible_with_workflow: false,
      support_level: "Conda Only",
      incompatibility_reasons: [],
    },
  ],
  workflow_profiles: [
    {
      profile: {
        profile_id: "personal_docker",
        server_id: "current",
        profile_kind: "personal_docker",
        executor: "local",
        packaging_mode: "container",
        container_runtime: "docker",
        work_dir: "~/.bioflow/runs/work",
        output_dir: "~/.bioflow/runs/output",
        cache_dir: "~/.bioflow/cache/containers",
      },
      available_on_server: true,
      compatible_with_workflow: false,
      support_level: "Conda Only",
      incompatibility_reasons: ["personal_docker ❌ Unknown sample 缺少 runtime.container"],
    },
    {
      profile: {
        profile_id: "personal_conda",
        server_id: "current",
        profile_kind: "personal_conda",
        executor: "local",
        packaging_mode: "conda",
        container_runtime: "",
        work_dir: "~/.bioflow/runs/work",
        output_dir: "~/.bioflow/runs/output",
        cache_dir: "~/.bioflow/cache/conda",
      },
      available_on_server: true,
      compatible_with_workflow: true,
      support_level: "Conda Only",
      incompatibility_reasons: [],
    },
  ],
  selected_profile: {
    profile_id: "personal_conda",
    server_id: "current",
    profile_kind: "personal_conda",
    executor: "local",
    packaging_mode: "conda",
    container_runtime: "",
    work_dir: "~/.bioflow/runs/work",
    output_dir: "~/.bioflow/runs/output",
    cache_dir: "~/.bioflow/cache/conda",
  },
  selection_reason: "服务器推荐 personal_docker，但当前 workflow 改用 personal_conda",
} as const;

test("parseWorkflowCompatibilitySummary keeps backend-selected profile and server/workflow lists", () => {
  const summary = parseWorkflowCompatibilitySummary(payload);
  assert.ok(summary);
  assert.equal(summary.selected_profile?.profile_id, "personal_conda");
  assert.equal(summary.server_profiles.length, 2);
  assert.equal(summary.workflow_profiles[0]?.compatible_with_workflow, false);
  assert.match(summary.selection_reason, /改用 personal_conda/);
});

test("summarizeWorkflowCompatibility reports the backend-selected profile", () => {
  const summary = parseWorkflowCompatibilitySummary(payload);
  assert.ok(summary);
  assert.equal(summarizeWorkflowCompatibility(summary, ""), "服务器可用 2 项 · 当前 workflow 可用 1 项 · 选定 personal_conda");
});

test("emptyWorkflowCompatibilitySummary is safe for initial render", () => {
  const summary = emptyWorkflowCompatibilitySummary();
  assert.equal(summary.server_profiles.length, 0);
  assert.equal(summary.selected_profile, null);
  assert.match(summarizeWorkflowCompatibility(summary, ""), /保存 workflow 后即可获取兼容性/);
});
