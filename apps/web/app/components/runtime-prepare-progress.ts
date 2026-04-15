export type RuntimeDecisionOption =
  | "use_docker"
  | "use_podman"
  | "self_install_docker"
  | "assistant_install_docker"
  | "fallback_conda";

export type BootstrapStep = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  message?: string;
};

export type InstallSnapshot = {
  job_id: string;
  status: string;
  done: boolean;
  ok: boolean;
  message: string;
  log_text: string;
  progress?: {
    kind?: string;
    profile_kind?: string;
    steps?: BootstrapStep[];
  };
};

type InstallTarget = "workflow_runtime" | "docker_runtime" | "";

type BuildRuntimePrepareViewArgs = {
  selectedDecision: RuntimeDecisionOption | null;
  installTarget: InstallTarget;
  snapshot: InstallSnapshot | null;
  installRunning: boolean;
};

type RuntimePrepareView = {
  steps: BootstrapStep[];
  emptyLogText: string;
};

const DOCKER_RUNTIME_STEPS: BootstrapStep[] = [
  { key: "sudo", label: "校验 sudo / root 权限", status: "pending" },
  { key: "download", label: "下载 Docker 安装脚本", status: "pending" },
  { key: "install", label: "安装 Docker", status: "pending" },
  { key: "service", label: "启动 Docker 服务", status: "pending" },
  { key: "verify", label: "验证 Docker 并提示重新检测", status: "pending" },
];

const WORKFLOW_RUNTIME_STEP_PRESETS: Record<string, { steps: BootstrapStep[]; emptyLogText: string }> = {
  use_docker: {
    steps: [
      { key: "java", label: "校验 Java 17-25", status: "pending" },
      { key: "docker", label: "验证 Docker", status: "pending" },
      { key: "nextflow", label: "准备 Nextflow", status: "pending" },
      { key: "runtime_dirs", label: "创建运行目录", status: "pending" },
      { key: "verification", label: "验证安装", status: "pending" },
    ],
    emptyLogText: "等待开始准备 Docker Runtime...",
  },
  use_podman: {
    steps: [
      { key: "java", label: "校验 Java 17-25", status: "pending" },
      { key: "podman", label: "验证 Podman", status: "pending" },
      { key: "nextflow", label: "准备 Nextflow", status: "pending" },
      { key: "runtime_dirs", label: "创建运行目录", status: "pending" },
      { key: "verification", label: "验证安装", status: "pending" },
    ],
    emptyLogText: "等待开始准备 Podman Runtime...",
  },
  fallback_conda: {
    steps: [
      { key: "java", label: "校验 Java", status: "pending" },
      { key: "nextflow", label: "安装 Nextflow", status: "pending" },
      { key: "micromamba", label: "安装 Micromamba", status: "pending" },
      { key: "runtime_dirs", label: "创建运行目录", status: "pending" },
      { key: "verification", label: "验证安装", status: "pending" },
    ],
    emptyLogText: "等待开始准备 Conda Runtime...",
  },
  self_install_docker: {
    steps: [
      { key: "manual_install", label: "等待自行安装 Docker", status: "pending" },
      { key: "recheck", label: "重新检测 Docker", status: "pending" },
      { key: "verification", label: "验证安装", status: "pending" },
    ],
    emptyLogText: "等待你完成 Docker 安装后重新检测...",
  },
};

function cloneSteps(steps: BootstrapStep[]): BootstrapStep[] {
  return steps.map((step) => ({ ...step }));
}

function applyTerminalState(
  steps: BootstrapStep[],
  args: {
    done: boolean;
    message: string;
  }
): BootstrapStep[] {
  return steps.map((step, index) => ({
    ...step,
    status: args.done ? "done" : "failed",
    message: index === steps.length - 1 && args.message ? args.message : step.message,
  }));
}

function applyRunningFallback(steps: BootstrapStep[]): BootstrapStep[] {
  if (steps.length === 0) {
    return [];
  }
  return steps.map((step, index) => ({
    ...step,
    status: index === 0 ? "running" : "pending",
  }));
}

function ensureVisibleRunningStep(steps: BootstrapStep[]): BootstrapStep[] {
  if (steps.length === 0) {
    return [];
  }
  if (steps.some((step) => step.status === "running")) {
    return steps;
  }
  const nextPendingIndex = steps.findIndex((step) => step.status === "pending");
  if (nextPendingIndex === -1) {
    return steps;
  }
  return steps.map((step, index) => ({
    ...step,
    status: index === nextPendingIndex ? "running" : step.status,
  }));
}

export function buildRuntimePrepareView(args: BuildRuntimePrepareViewArgs): RuntimePrepareView {
  const mode =
    args.installTarget === "docker_runtime"
      ? "docker_runtime"
      : args.selectedDecision || "fallback_conda";

  if (args.snapshot?.progress?.steps?.length) {
    const snapshotSteps = cloneSteps(args.snapshot.progress.steps);
    return {
      steps:
        args.snapshot.status === "running" && args.installRunning
          ? ensureVisibleRunningStep(snapshotSteps)
          : snapshotSteps,
      emptyLogText:
        mode === "docker_runtime"
          ? "等待开始协助安装 Docker..."
          : WORKFLOW_RUNTIME_STEP_PRESETS[mode]?.emptyLogText || "等待开始准备 Runtime...",
    };
  }

  if (mode === "docker_runtime") {
    const base = cloneSteps(DOCKER_RUNTIME_STEPS);
    if (!args.snapshot) {
      return {
        steps: args.installRunning ? applyRunningFallback(base) : base,
        emptyLogText: "等待开始协助安装 Docker...",
      };
    }
    if (args.snapshot.status === "done" || args.snapshot.status === "failed") {
      return {
        steps: applyTerminalState(base, { done: args.snapshot.status === "done", message: args.snapshot.message || "" }),
        emptyLogText: "等待开始协助安装 Docker...",
      };
    }
    return {
      steps: base.map((step, index) => ({
        ...step,
        status: index < 4 ? "running" : "pending",
      })),
      emptyLogText: "等待开始协助安装 Docker...",
    };
  }

  const preset = WORKFLOW_RUNTIME_STEP_PRESETS[mode] || WORKFLOW_RUNTIME_STEP_PRESETS.fallback_conda;
  if (!args.snapshot) {
    const base = cloneSteps(preset.steps);
    return {
      steps: args.installRunning ? applyRunningFallback(base) : base,
      emptyLogText: preset.emptyLogText,
    };
  }
  if (args.snapshot.status === "done" || args.snapshot.status === "failed") {
    return {
      steps: applyTerminalState(cloneSteps(preset.steps), { done: args.snapshot.status === "done", message: args.snapshot.message || "" }),
      emptyLogText: preset.emptyLogText,
    };
  }
  return {
    steps: applyRunningFallback(cloneSteps(preset.steps)),
    emptyLogText: preset.emptyLogText,
  };
}
