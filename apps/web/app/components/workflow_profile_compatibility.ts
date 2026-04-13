"use client";

import type {
  ServerDoctorReport,
  WorkflowCompatibilitySummary,
  WorkflowProfileCompatibility,
  WorkflowServerProfile,
  WorkflowSpecView,
  WorkflowSupportLevel,
  WorkflowToolDescriptor,
  WorkflowToolRuntime,
} from "./detection_workspace_types";

type RuntimeCapabilities = NonNullable<ServerDoctorReport["runtime_capabilities"]>;

type ProfileTemplate = {
  profile_id: WorkflowServerProfile["profile_id"];
  executor: string;
  packaging_mode: WorkflowServerProfile["packaging_mode"];
  container_runtime: string;
  isAvailable(caps: RuntimeCapabilities | null): boolean;
};

const DEFAULT_WORK_DIR = "~/.bioflow/runs/work";
const DEFAULT_OUTPUT_DIR = "~/.bioflow/runs/output";
const DEFAULT_CONDA_CACHE_DIR = "~/.bioflow/cache/conda";
const DEFAULT_CONTAINER_CACHE_DIR = "~/.bioflow/cache/containers";

const PROFILE_TEMPLATES: ProfileTemplate[] = [
  {
    profile_id: "hpc_slurm_apptainer",
    executor: "slurm",
    packaging_mode: "container",
    container_runtime: "apptainer",
    isAvailable: (caps) => Boolean(caps?.sbatch.available && caps?.apptainer.available),
  },
  {
    profile_id: "hpc_slurm_conda",
    executor: "slurm",
    packaging_mode: "conda",
    container_runtime: "",
    isAvailable: (caps) => Boolean(caps?.sbatch.available && (caps?.micromamba.available || caps?.conda.available)),
  },
  {
    profile_id: "personal_docker",
    executor: "local",
    packaging_mode: "container",
    container_runtime: "docker",
    isAvailable: (caps) => Boolean(caps?.docker.available),
  },
  {
    profile_id: "personal_podman",
    executor: "local",
    packaging_mode: "container",
    container_runtime: "podman",
    isAvailable: (caps) => Boolean(caps?.podman.available),
  },
  {
    profile_id: "personal_conda",
    executor: "local",
    packaging_mode: "conda",
    container_runtime: "",
    isAvailable: (caps) => Boolean(caps?.micromamba.available || caps?.conda.available),
  },
];

const SUPPORT_LEVEL_ORDER: Record<WorkflowSupportLevel, number> = {
  "Production Ready": 0,
  "Conda Only": 1,
  "Legacy": 2,
};

export function parseWorkflowToolDescriptor(value: unknown): WorkflowToolDescriptor | null {
  if (!isRecord(value)) {
    return null;
  }
  const toolId = safeText(value.id || value.tool_id);
  if (!toolId) {
    return null;
  }
  const workflowSupport = parseWorkflowToolSupport(value.workflow_support);
  return {
    tool_id: toolId,
    name: safeText(value.name, toolId),
    workflow_support: workflowSupport,
  };
}

export function buildWorkflowCompatibilitySummary(
  doctor: ServerDoctorReport | null,
  workflow: WorkflowSpecView | null,
  descriptors: Record<string, WorkflowToolDescriptor>,
): WorkflowCompatibilitySummary {
  const serverProfiles = buildServerProfiles(doctor);
  const workflowProfiles = serverProfiles.map((entry) => evaluateProfileCompatibility(entry.profile, workflow, descriptors));
  const compatibleProfiles = workflowProfiles.filter((entry) => entry.available_on_server && entry.compatible_with_workflow);
  const preferredProfileId = safeText(doctor?.recommended_profile_details?.profile_id || doctor?.recommended_profile);
  const selectedProfile =
    compatibleProfiles.find((entry) => entry.profile.profile_id === preferredProfileId)?.profile ||
    compatibleProfiles[0]?.profile ||
    null;

  let selectionReason = "";
  if (!doctor) {
    selectionReason = "等待服务器 doctor 完成后再选择 workflow profile。";
  } else if (selectedProfile && selectedProfile.profile_id === preferredProfileId) {
    selectionReason = `使用服务器推荐 profile：${selectedProfile.profile_id}`;
  } else if (selectedProfile && preferredProfileId) {
    selectionReason = `服务器推荐 ${preferredProfileId}，但当前 workflow 改用 ${selectedProfile.profile_id}`;
  } else if (selectedProfile) {
    selectionReason = `当前 workflow 可用 profile：${selectedProfile.profile_id}`;
  } else if (!workflow?.nodes.length) {
    selectionReason = "当前 workflow 还没有步骤，先展示服务器可用 profile。";
  } else {
    selectionReason = "当前 workflow 没有可直接提交的 profile，请先修复不兼容步骤。";
  }

  return {
    server_profiles: serverProfiles,
    workflow_profiles: workflowProfiles,
    selected_profile: selectedProfile,
    selection_reason: selectionReason,
  };
}

export function summarizeWorkflowCompatibility(summary: WorkflowCompatibilitySummary, doctorError: string): string {
  if (doctorError) {
    return `连接可用，但运行时探测失败：${doctorError}`;
  }
  if (!summary.server_profiles.length) {
    return "正在检测服务器运行时。";
  }
  const serverAvailable = summary.server_profiles.filter((item) => item.available_on_server).length;
  const workflowAvailable = summary.workflow_profiles.filter((item) => item.compatible_with_workflow).length;
  const selected = summary.selected_profile?.profile_id || "未选定";
  return `服务器可用 ${serverAvailable} 项 · 当前 workflow 可用 ${workflowAvailable} 项 · 选定 ${selected}`;
}

function buildServerProfiles(doctor: ServerDoctorReport | null): WorkflowProfileCompatibility[] {
  const caps = doctor?.runtime_capabilities || null;
  const base = doctor?.recommended_profile_details || null;
  return PROFILE_TEMPLATES.map((template): WorkflowProfileCompatibility => {
    const available = template.isAvailable(caps);
    return {
      profile: {
        profile_id: template.profile_id,
        server_id: doctor?.server_id || base?.server_id || "current",
        profile_kind: template.profile_id,
        executor: template.executor,
        packaging_mode: template.packaging_mode,
        container_runtime: template.container_runtime,
        work_dir: base?.work_dir || DEFAULT_WORK_DIR,
        output_dir: base?.output_dir || DEFAULT_OUTPUT_DIR,
        cache_dir:
          template.profile_id === base?.profile_id
            ? base.cache_dir
            : template.packaging_mode === "container"
              ? DEFAULT_CONTAINER_CACHE_DIR
              : DEFAULT_CONDA_CACHE_DIR,
      },
      available_on_server: available,
      compatible_with_workflow: false,
      support_level: "Legacy",
      incompatibility_reasons: available ? [] : [`服务器缺少 ${profileCapabilityLabel(template.profile_id)}`],
    };
  }).filter((item) => item.available_on_server);
}

function evaluateProfileCompatibility(
  profile: WorkflowServerProfile,
  workflow: WorkflowSpecView | null,
  descriptors: Record<string, WorkflowToolDescriptor>,
): WorkflowProfileCompatibility {
  const reasons = new Set<string>();
  let supportLevel: WorkflowSupportLevel = "Production Ready";

  for (const node of workflow?.nodes || []) {
    const descriptor = descriptors[node.tool_id];
    if (!descriptor) {
      reasons.add(`${node.label || node.node_id}（${node.tool_id}）缺少描述符，无法评估兼容性`);
      supportLevel = maxSupportLevel(supportLevel, "Legacy");
      continue;
    }
    const workflowSupport = descriptor.workflow_support;
    if (!workflowSupport) {
      reasons.add(`${descriptor.name} 缺少 workflow_support 元数据`);
      supportLevel = maxSupportLevel(supportLevel, "Legacy");
      continue;
    }
    supportLevel = maxSupportLevel(supportLevel, workflowSupport.support_level);
    for (const error of workflowSupport.validation_errors) {
      reasons.add(`${descriptor.name}：${error}`);
    }
    if (profile.packaging_mode === "container" && !workflowSupport.runtime.container) {
      reasons.add(`${profile.profile_id} ❌ ${descriptor.name} 缺少 runtime.container`);
    }
    if (profile.packaging_mode === "conda" && !workflowSupport.runtime.conda) {
      reasons.add(`${profile.profile_id} ❌ ${descriptor.name} 缺少 runtime.conda`);
    }
  }

  return {
    profile,
    available_on_server: true,
    compatible_with_workflow: reasons.size === 0,
    support_level: supportLevel,
    incompatibility_reasons: Array.from(reasons),
  };
}

function parseWorkflowToolSupport(value: unknown): WorkflowToolDescriptor["workflow_support"] {
  if (!isRecord(value)) {
    return null;
  }
  const supportLevel = safeText(value.support_level) as WorkflowSupportLevel;
  if (supportLevel !== "Production Ready" && supportLevel !== "Conda Only" && supportLevel !== "Legacy") {
    return null;
  }
  return {
    support_level: supportLevel,
    workflow_ready: Boolean(value.workflow_ready),
    validation_errors: Array.isArray(value.validation_errors) ? value.validation_errors.map((item) => safeText(item)).filter(Boolean) : [],
    runtime: parseWorkflowToolRuntime(value.runtime),
  };
}

function parseWorkflowToolRuntime(value: unknown): WorkflowToolRuntime {
  if (!isRecord(value)) {
    return { container: "", conda: "", conda_env_name: "" };
  }
  return {
    container: safeText(value.container),
    conda: safeText(value.conda),
    conda_env_name: safeText(value.conda_env_name),
  };
}

function profileCapabilityLabel(profileId: string): string {
  switch (profileId) {
    case "hpc_slurm_apptainer":
      return "sbatch + apptainer";
    case "hpc_slurm_conda":
      return "sbatch + micromamba/conda";
    case "personal_docker":
      return "Docker";
    case "personal_podman":
      return "Podman";
    case "personal_conda":
      return "micromamba/conda";
    default:
      return profileId;
  }
}

function maxSupportLevel(left: WorkflowSupportLevel, right: WorkflowSupportLevel): WorkflowSupportLevel {
  return SUPPORT_LEVEL_ORDER[left] >= SUPPORT_LEVEL_ORDER[right] ? left : right;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function safeText(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}
