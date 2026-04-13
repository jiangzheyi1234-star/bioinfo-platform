import assert from "node:assert/strict";
import test from "node:test";

import { buildWorkflowCompatibilitySummary } from "./workflow_profile_compatibility.ts";

const doctor = {
  server_id: "current",
  doctor_phase: "workflow_runtime",
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
  preflight: null,
  env_status: null,
} as const;

test("all container-ready nodes keep docker compatible", () => {
  const summary = buildWorkflowCompatibilitySummary(
    doctor,
    {
      workflow_id: "wf",
      name: "wf",
      version: "0.1.0",
      nodes: [{ node_id: "n1", tool_id: "fastp", label: "Fastp", params: {} }],
      edges: [],
      params_schema: {},
    },
    {
      fastp: {
        tool_id: "fastp",
        name: "fastp",
        workflow_support: {
          support_level: "Production Ready",
          workflow_ready: true,
          validation_errors: [],
          runtime: {
            container: "quay.io/biocontainers/fastp:0.23.4",
            conda: "fastp=0.23.4",
            conda_env_name: "fastp_env",
          },
        },
      },
    },
  );

  const docker = summary.workflow_profiles.find((item) => item.profile.profile_id === "personal_docker");
  assert.ok(docker);
  assert.equal(docker.compatible_with_workflow, true);
  assert.equal(summary.selected_profile?.profile_id, "personal_docker");
});

test("missing runtime.container makes docker incompatible with an explicit reason", () => {
  const summary = buildWorkflowCompatibilitySummary(
    doctor,
    {
      workflow_id: "wf",
      name: "wf",
      version: "0.1.0",
      nodes: [{ node_id: "n1", tool_id: "unknown_sample_detection", label: "Unknown sample", params: {} }],
      edges: [],
      params_schema: {},
    },
    {
      unknown_sample_detection: {
        tool_id: "unknown_sample_detection",
        name: "Unknown sample",
        workflow_support: {
          support_level: "Conda Only",
          workflow_ready: true,
          validation_errors: [],
          runtime: {
            container: "",
            conda: "fastp=0.23.4 hostile=1.1.0 centrifuge=1.0.4",
            conda_env_name: "unknown_sample_detection_env",
          },
        },
      },
    },
  );

  const docker = summary.workflow_profiles.find((item) => item.profile.profile_id === "personal_docker");
  const conda = summary.workflow_profiles.find((item) => item.profile.profile_id === "personal_conda");
  assert.ok(docker);
  assert.ok(conda);
  assert.equal(docker.compatible_with_workflow, false);
  assert.match(docker.incompatibility_reasons.join(" "), /缺少 runtime\.container/);
  assert.equal(conda.compatible_with_workflow, true);
  assert.equal(summary.selected_profile?.profile_id, "personal_conda");
});

test("empty workflows still expose server-available profiles without false incompatibility", () => {
  const summary = buildWorkflowCompatibilitySummary(
    doctor,
    {
      workflow_id: "wf",
      name: "wf",
      version: "0.1.0",
      nodes: [],
      edges: [],
      params_schema: {},
    },
    {},
  );

  assert.ok(summary.server_profiles.length >= 2);
  assert.equal(summary.workflow_profiles.every((item) => item.compatible_with_workflow), true);
});
