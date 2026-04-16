"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Circle, Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  formatApiFetchError,
  formatRuntimeInspectionError,
  getRecommendedDecision,
  isRuntimeReady,
  loadRuntimeInspection,
  type EnvStatusPayload,
  type PreflightPayload,
  type RuntimeInspection,
} from "@/app/components/runtime-inspection";
import { requestLocalApiJson } from "@/app/lib/local-api-client";
import { type RuntimeDecisionOption } from "@/app/components/runtime-prepare-progress";

type SSHStatus = {
  connected: boolean;
  host: string;
  port: number;
  user: string;
};

type RuntimeCheckItem = {
  key: string;
  label: string;
  status: "ready" | "missing" | "warn" | "blocked";
  value: string;
  message: string;
};

type RuntimeReadySummary = {
  selectedProfile: string;
  runtimeHome: string;
  nextflowPath: string;
  micromambaPath: string;
  javaPath?: string;
};

type CheckSection = {
  key: string;
  title: string;
  description: string;
  items: RuntimeCheckItem[];
};

type InstallTarget = "workflow_runtime" | "docker_runtime" | "";

type PrepareServerWizardProps = {
  open: boolean;
  sshStatus: SSHStatus | null;
  runtimeReady?: boolean;
  resolvedRuntime?: {
    hostKey?: string;
    nextflowPath?: string;
    javaPath?: string;
    selectedProfile?: string;
    verificationStatus?: string;
  } | null;
  onOpenChange: (open: boolean) => void;
  onPrepared?: (resolved?: { nextflowPath?: string; javaPath?: string; selectedProfile?: string }) => void;
  onOpenTerminal?: () => void;
  onSendTerminalCommand?: (command: string) => Promise<boolean>;
};

type LocalResolvedRuntime = NonNullable<PrepareServerWizardProps["resolvedRuntime"]>;

function toLocalResolvedRuntime(
  resolvedRuntime: RuntimeInspection["resolvedRuntime"] | null | undefined
): LocalResolvedRuntime | null {
  if (!resolvedRuntime) {
    return null;
  }
  return {
    hostKey: String(resolvedRuntime.host_key || "").trim(),
    nextflowPath: String(resolvedRuntime.nextflow_path || "").trim(),
    javaPath: String(resolvedRuntime.java_path || "").trim(),
    selectedProfile: String(resolvedRuntime.selected_profile || "").trim(),
    verificationStatus: String(resolvedRuntime.verification_status || "").trim(),
  };
}

function toInspectionResolvedRuntime(
  resolvedRuntime: PrepareServerWizardProps["resolvedRuntime"]
): RuntimeInspection["resolvedRuntime"] | null {
  if (!resolvedRuntime) {
    return null;
  }
  return {
    host_key: resolvedRuntime.hostKey,
    nextflow_path: resolvedRuntime.nextflowPath,
    java_path: resolvedRuntime.javaPath,
    selected_profile: resolvedRuntime.selectedProfile,
    verification_status: resolvedRuntime.verificationStatus,
  };
}

function getCheckItemValue(items: RuntimeCheckItem[], key: string, fallback: string): string {
  return items.find((item) => item.key === key)?.value || fallback;
}

type RemediationCommand = {
  key: string;
  label: string;
  description: string;
  command: string;
};

type RemediationSection = {
  key: "java" | "nextflow" | "docker";
  title: string;
  status: "ready" | "repair" | "blocked";
  summary: string;
  commands: RemediationCommand[];
};

function extractLogField(logText: string, key: string): string {
  const pattern = new RegExp(`^${key}=(.+)$`, "m");
  const match = String(logText || "").match(pattern);
  return match?.[1]?.trim() || "";
}

function runtimeHostKey(status: SSHStatus | null): string {
  if (!status) {
    return "";
  }
  return `${status.user}@${status.host}:${status.port}`;
}

function toItemStatus(status: "ok" | "warn" | "fail"): RuntimeCheckItem["status"] {
  if (status === "ok") return "ready";
  if (status === "warn") return "warn";
  return "missing";
}

function toRuntimeStatus(
  check:
    | {
        status: "ok" | "warn" | "fail";
        value: string;
        message: string;
      }
    | undefined
): RuntimeCheckItem["status"] {
  if (!check) return "missing";
  if (check.status === "ok") return "ready";
  if (check.status === "fail") return "missing";
  if (/(不可|无法|read_only|受限)/.test(check.message) || check.value === "installed") {
    return "blocked";
  }
  return "warn";
}

function normalizeValue(value: string): string {
  switch (value) {
    case "usable":
      return "可直接使用";
    case "installed":
      return "已安装";
    case "available":
      return "已检测到";
    case "missing":
      return "未检测到";
    case "writable":
      return "可写";
    case "read_only":
      return "只读";
    default:
      return value;
  }
}

function buildChecklist(
  preflight: PreflightPayload | null,
  envStatus: EnvStatusPayload | null,
  resolvedRuntime?: PrepareServerWizardProps["resolvedRuntime"]
): RuntimeCheckItem[] {
  if (!preflight) {
    return [];
  }

  const checksByKey = new Map((preflight.checks || []).map((item) => [item.key, item]));
  const runtime = preflight.runtime_capabilities || {};
  const condaInstalled = envStatus?.conda_runtime?.installed === true;
  const condaExecutable = envStatus?.conda_runtime?.conda_executable || "";
  const resolvedVerified = resolvedRuntime?.hostKey === undefined || resolvedRuntime?.verificationStatus === "verified";
  const resolvedJavaAvailable = Boolean(resolvedVerified && resolvedRuntime?.javaPath);
  const resolvedNextflowAvailable = Boolean(resolvedVerified && resolvedRuntime?.nextflowPath);

  const makeRuntimeItem = (args: {
    key: string;
    fallbackLabel: string;
    fallbackStatus: RuntimeCheckItem["status"];
    fallbackValue: string;
    fallbackMessage: string;
  }): RuntimeCheckItem => {
    const check = checksByKey.get(args.key);
    return {
      key: args.key,
      label: check?.label || args.fallbackLabel,
      status: check ? toRuntimeStatus(check) : args.fallbackStatus,
      value: normalizeValue(String(check?.value || args.fallbackValue)),
      message: check?.message || args.fallbackMessage,
    };
  };

  const items: RuntimeCheckItem[] = [
    {
      key: "java",
      label: "Java 17+",
      status: runtime.java?.usable || resolvedJavaAvailable ? "ready" : runtime.java?.available ? "blocked" : "missing",
      value: normalizeValue(
        String(resolvedRuntime?.javaPath || runtime.java?.version || (runtime.java?.available ? "installed" : "missing"))
      ),
      message: runtime.java?.usable || resolvedJavaAvailable
        ? "已检测到 Java，可用于运行 Nextflow"
        : runtime.java?.message
          ? runtime.java.message
          : runtime.java?.available
            ? "已检测到 Java，但当前不可正常调用"
            : "未检测到 Java，无法运行 Nextflow",
    },
    {
      key: "nextflow",
      label: "Nextflow",
      status: runtime.nextflow?.usable || resolvedNextflowAvailable ? "ready" : runtime.nextflow?.available ? "blocked" : "missing",
      value: normalizeValue(
        String(resolvedRuntime?.nextflowPath || runtime.nextflow?.version || (runtime.nextflow?.available ? "installed" : "missing"))
      ),
      message: runtime.nextflow?.usable || resolvedNextflowAvailable
        ? "已检测到 Nextflow"
        : runtime.nextflow?.message
          ? runtime.nextflow.message
          : runtime.nextflow?.available
            ? "已检测到 Nextflow，但当前不可正常调用"
            : "未检测到 Nextflow",
    },
    makeRuntimeItem({
      key: "docker",
      fallbackLabel: "Docker",
      fallbackStatus: runtime.docker?.usable ? "ready" : runtime.docker?.available ? "blocked" : "missing",
      fallbackValue: runtime.docker?.usable ? "usable" : runtime.docker?.available ? "installed" : "missing",
      fallbackMessage: runtime.docker?.usable
        ? "已检测到 Docker，可优先使用容器模式"
        : runtime.docker?.available
          ? "已检测到 Docker，但当前用户不可直接使用"
          : "未检测到 Docker",
    }),
    makeRuntimeItem({
      key: "podman",
      fallbackLabel: "Podman",
      fallbackStatus: runtime.podman?.usable ? "ready" : runtime.podman?.available ? "blocked" : "missing",
      fallbackValue: runtime.podman?.usable ? "usable" : runtime.podman?.available ? "installed" : "missing",
      fallbackMessage: runtime.podman?.usable
        ? "已检测到 Podman，可作为容器模式替代"
        : runtime.podman?.available
          ? "已检测到 Podman，但当前用户不可直接使用"
          : "未检测到 Podman",
    }),
    makeRuntimeItem({
      key: "apptainer",
      fallbackLabel: "Apptainer",
      fallbackStatus: runtime.apptainer?.usable ? "ready" : runtime.apptainer?.available ? "blocked" : "missing",
      fallbackValue: runtime.apptainer?.usable ? "usable" : runtime.apptainer?.available ? "installed" : "missing",
      fallbackMessage: runtime.apptainer?.usable
        ? "已检测到 Apptainer（更适合共享/HPC 场景）"
        : runtime.apptainer?.available
          ? "已检测到 Apptainer，但当前不可正常调用"
          : "未检测到 Apptainer（个人服务器不作为默认）",
    }),
    makeRuntimeItem({
      key: "micromamba",
      fallbackLabel: "Micromamba",
      fallbackStatus: runtime.micromamba?.usable ? "ready" : runtime.micromamba?.available ? "blocked" : "missing",
      fallbackValue: runtime.micromamba?.usable ? "usable" : runtime.micromamba?.available ? "installed" : "missing",
      fallbackMessage: runtime.micromamba?.usable
        ? "已检测到 Micromamba"
        : runtime.micromamba?.available
          ? "已检测到 Micromamba，但当前不可正常调用"
          : "未检测到 Micromamba",
    }),
    makeRuntimeItem({
      key: "conda",
      fallbackLabel: "Conda",
      fallbackStatus: runtime.conda?.usable || condaInstalled ? "ready" : runtime.conda?.available ? "blocked" : "missing",
      fallbackValue: condaExecutable || (runtime.conda?.usable ? "usable" : runtime.conda?.available ? "installed" : "missing"),
      fallbackMessage:
        runtime.conda?.usable || condaInstalled
          ? "已检测到 Conda Runtime"
          : runtime.conda?.available
            ? "已检测到 Conda，但当前不可正常调用"
            : "未检测到 Conda Runtime",
    }),
  ];

  for (const key of ["home_writable", "disk", "bash", "downloader"] as const) {
    const item = checksByKey.get(key);
    if (!item) continue;
    items.push({
      key,
      label: item.label,
      status: toItemStatus(item.status),
      value: normalizeValue(item.value),
      message: item.message,
    });
  }

  return items;
}

function getStatusPresentation(item: RuntimeCheckItem): {
  label: string;
  badgeClassName: string;
  descriptionClassName: string;
} {
  if (item.status === "ready") {
    const label = item.value === "usable" ? "可直接使用" : "已就绪";
    return {
      label,
      badgeClassName: "border-emerald-100 bg-emerald-50 text-emerald-700",
      descriptionClassName: "text-emerald-600",
    };
  }

  if (item.status === "warn") {
    const label = item.value === "已安装" ? "已安装，待确认" : "需要确认";
    return {
      label,
      badgeClassName: "border-amber-100 bg-amber-50 text-amber-700",
      descriptionClassName: "text-amber-600",
    };
  }

  if (item.status === "blocked") {
    return {
      label: item.value === "已安装" ? "已安装，受限" : "受限",
      badgeClassName: "border-orange-100 bg-orange-50 text-orange-700",
      descriptionClassName: "text-orange-600",
    };
  }

  return {
    label: "缺失",
    badgeClassName: "border-red-100 bg-red-50 text-red-700",
    descriptionClassName: "text-red-600",
  };
}

function buildSections(items: RuntimeCheckItem[]): CheckSection[] {
  const groups = [
    {
      key: "resolution-order",
      title: "自动检测顺序",
      description: "按 Bash → Java → Nextflow 校验固定运行入口，避免依赖 PATH / shell 自动加载。",
      keys: ["bash", "java", "nextflow"],
    },
    {
      key: "execution-backend",
      title: "执行后端",
      description: "优先确认 Docker / Podman 是否可直接作为统一执行后端。",
      keys: ["docker", "podman", "apptainer"],
    },
    {
      key: "optional-fallback",
      title: "可选 fallback",
      description: "Micromamba / Conda 仅作为补位能力，不应阻塞一键配置主路径。",
      keys: ["micromamba", "conda"],
    },
    {
      key: "server-baseline",
      title: "服务器基线",
      description: "影响下载、目录创建与后续运行目录初始化。",
      keys: ["home_writable", "disk", "downloader", "sha256sum", "screen"],
    },
  ] as const;

  return groups
    .map((group) => ({
      key: group.key,
      title: group.title,
      description: group.description,
      items: items.filter((item) => (group.keys as readonly string[]).includes(item.key)),
    }))
    .filter((section) => section.items.length > 0);
}

function hasSectionWarnings(section: CheckSection): boolean {
  return section.items.some((item) => item.status === "warn" || item.status === "blocked");
}

function getRecommendedExplanation(args: {
  dockerUsable: boolean;
  podmanUsable: boolean;
  preflight: PreflightPayload | null;
}): string {
  if (!args.preflight) {
    return "请先完成一次真实检测，系统再按固定路径与推荐 profile 自动推进。";
  }
  if (args.dockerUsable) {
    return "已检测到 Docker，配置流程会优先固定 Docker 执行路径。";
  }
  if (args.podmanUsable) {
    return "未检测到 Docker，但 Podman 可用，配置流程会按 Podman 路线继续。";
  }
  return "未检测到可用容器运行时，将继续准备 Micromamba / Conda fallback；Conda 仅作为可选补位，不会阻塞整体检测。";
}

function buildRemediationSections(args: {
  checklist: RuntimeCheckItem[];
  preflight: PreflightPayload | null;
  resolvedRuntime?: PrepareServerWizardProps["resolvedRuntime"];
}): RemediationSection[] {
  const { checklist, preflight, resolvedRuntime } = args;
  const javaItem = checklist.find((item) => item.key === "java");
  const nextflowItem = checklist.find((item) => item.key === "nextflow");
  const dockerItem = checklist.find((item) => item.key === "docker");

  const javaReady = javaItem?.status === "ready";
  const nextflowReady = nextflowItem?.status === "ready";
  const dockerReady = dockerItem?.status === "ready";
  const nextflowDetectedPath = String(resolvedRuntime?.nextflowPath || nextflowItem?.value || "").trim();

  const javaSection: RemediationSection = javaReady
    ? {
        key: "java",
        title: "Java 修复",
        status: "ready",
        summary: "Java 已通过检测，无需额外修复。",
        commands: [],
      }
    : {
        key: "java",
        title: "Java 修复",
        status: "repair",
        summary: "Java 仍未就绪。请通过终端逐条发送命令并在终端确认输出，然后重新检测。",
        commands: [
          {
            key: "java-install-sdkman",
            label: "发送 SDKMAN 安装命令",
            description: "先安装 SDKMAN，便于在用户态安装 Java。",
            command: `bash -lc 'curl -s https://get.sdkman.io | bash'`,
          },
          {
            key: "java-source-sdkman",
            label: "发送 SDKMAN 初始化命令",
            description: "加载 SDKMAN 环境，为后续 Java 安装做准备。",
            command: `bash -lc 'source "$HOME/.sdkman/bin/sdkman-init.sh"'`,
          },
          {
            key: "java-install",
            label: "发送 Java 安装命令",
            description: "显式安装符合要求的 Java 17 版本。",
            command: `bash -lc 'source "$HOME/.sdkman/bin/sdkman-init.sh" && sdk install java 17.0.10-tem'`,
          },
          {
            key: "java-verify",
            label: "发送 Java 验证命令",
            description: "检查 Java 版本是否已满足 Nextflow 要求。",
            command: `bash -lc 'java -version'`,
          },
        ],
      };

  const nextflowSection: RemediationSection = nextflowReady
    ? {
        key: "nextflow",
        title: "Nextflow 修复",
        status: "ready",
        summary: "Nextflow 已通过检测，无需额外修复。",
        commands: [],
      }
    : !javaReady
      ? {
          key: "nextflow",
          title: "Nextflow 修复",
          status: "blocked",
          summary: "请先修复 Java，再继续处理 Nextflow。命令发送成功不代表修复成功，仍需重新检测验证。",
          commands: [],
        }
      : {
          key: "nextflow",
          title: "Nextflow 修复",
          status: "repair",
          summary: "Nextflow 未就绪。请通过终端逐条发送命令，并在每一步后确认输出。",
          commands: [
            ...(nextflowDetectedPath && !/未检测到|已安装|missing|installed/i.test(nextflowDetectedPath)
              ? [
                  {
                    key: "nextflow-verify-existing",
                    label: "验证当前 Nextflow 路径",
                    description: "优先验证已检测到的固定路径，而不是依赖 PATH 漂移。",
                    command: `bash -lc '${nextflowDetectedPath.replace(/'/g, `'\"'\"'`)} info'`,
                  },
                ]
              : []),
            {
              key: "nextflow-install",
              label: "发送 Nextflow 安装命令",
              description: "显式安装/刷新用户态 Nextflow 到固定目录。",
              command:
                `bash -lc 'mkdir -p "$HOME/.local/bin" && cd "$HOME/.local/bin" && curl -fsSL https://get.nextflow.io | bash && chmod +x nextflow'`,
            },
            {
              key: "nextflow-verify",
              label: "发送 Nextflow 验证命令",
              description: "确认固定路径上的 Nextflow 可执行并返回版本/信息。",
              command: `bash -lc '"$HOME/.local/bin/nextflow" info'`,
            },
          ],
        };

  const dockerSection: RemediationSection = dockerReady
    ? {
        key: "docker",
        title: "Docker 修复",
        status: "ready",
        summary: "Docker 已通过检测，无需额外修复。",
        commands: [],
      }
    : {
        key: "docker",
        title: "Docker 修复",
        status: "repair",
        summary:
          preflight?.recommended_profile === "personal_podman"
            ? "当前推荐 profile 是 Podman，但若后续需要统一 Docker 执行后端，请先在终端完成显式 Docker 修复并重新检测。"
            : "Docker 尚未就绪。请通过终端逐条发送命令，修复后再重新检测。",
        commands: [
          {
            key: "docker-check-sudo",
            label: "发送 sudo 检查命令",
            description: "先确认当前用户是否具备安装 Docker 所需权限。",
            command: `bash -lc 'sudo -v'`,
          },
          {
            key: "docker-install",
            label: "发送 Docker 安装命令",
            description: "显式安装 Docker；命令发送后请在终端确认安装过程。",
            command: `bash -lc 'curl -fsSL https://get.docker.com | sudo sh'`,
          },
          {
            key: "docker-group",
            label: "发送 Docker 用户组命令",
            description: "将当前用户加入 docker 组，后续需重新登录/重连后再验证。",
            command: `bash -lc 'sudo usermod -aG docker "$USER"'`,
          },
          {
            key: "docker-verify",
            label: "发送 Docker 验证命令",
            description: "检查 Docker 是否已可调用。",
            command: `bash -lc 'docker --version'`,
          },
        ],
      };

  return [javaSection, nextflowSection, dockerSection];
}

function remediationBadge(section: RemediationSection): { label: string; className: string } {
  if (section.status === "ready") {
    return { label: "已就绪", className: "border-emerald-100 bg-emerald-50 text-emerald-700" };
  }
  if (section.status === "blocked") {
    return { label: "需先处理前置项", className: "border-amber-100 bg-amber-50 text-amber-700" };
  }
  return { label: "待终端修复", className: "border-blue-100 bg-blue-50 text-blue-700" };
}

function profileKindForDecision(selectedDecision: RuntimeDecisionOption | null): string {
  if (selectedDecision === "use_docker") return "personal_docker";
  if (selectedDecision === "use_podman") return "personal_podman";
  if (selectedDecision === "fallback_conda") return "personal_conda";
  return "";
}

function getBootstrapBlockReason(
  preflight: PreflightPayload | null,
  selectedDecision: RuntimeDecisionOption | null
): string {
  if (!preflight || !selectedDecision || selectedDecision === "self_install_docker") {
    return "";
  }

  const javaCheck = preflight.checks.find((item) => item.key === "java");
  const javaUsable = preflight.runtime_capabilities?.java?.usable === true;
  const javaBlockedMessage = javaCheck?.message || "当前服务器 Java 版本不满足 Nextflow 要求（需 17-25），请先修复 Java。";
  if (selectedDecision === "assistant_install_docker") {
    return javaUsable ? "" : javaBlockedMessage;
  }

  const profileKind = profileKindForDecision(selectedDecision);
  if (!profileKind) {
    return "";
  }
  if ((preflight.supported_profile_kinds || []).includes(profileKind)) {
    return "";
  }
  if (!javaUsable) {
    return javaBlockedMessage;
  }
  return `当前服务器尚未满足 ${profileKind} 的准备条件，请先补齐依赖并重新检测。`;
}

export function PrepareServerWizard({
  open,
  sshStatus,
  runtimeReady: runtimeReadyOverride,
  resolvedRuntime,
  onOpenChange,
  onPrepared,
  onOpenTerminal,
  onSendTerminalCommand,
}: PrepareServerWizardProps) {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [preflight, setPreflight] = useState<PreflightPayload | null>(null);
  const [envStatus, setEnvStatus] = useState<EnvStatusPayload | null>(null);
  const [detectedResolvedRuntime, setDetectedResolvedRuntime] = useState<PrepareServerWizardProps["resolvedRuntime"]>(resolvedRuntime ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedDecision, setSelectedDecision] = useState<RuntimeDecisionOption | null>(null);
  const [flowNotice, setFlowNotice] = useState("");
  const [resolvedNextflowPath, setResolvedNextflowPath] = useState("");
  const [resolvedJavaPath, setResolvedJavaPath] = useState("");
  const [sentRemediationKeys, setSentRemediationKeys] = useState<Record<string, boolean>>({});
  const currentHostKey = runtimeHostKey(sshStatus);
  const resolvedRuntimeForInspection = useMemo(() => toInspectionResolvedRuntime(detectedResolvedRuntime), [detectedResolvedRuntime]);

  const capabilities = preflight?.runtime_capabilities;
  const dockerUsable = capabilities?.docker?.usable === true;
  const podmanUsable = capabilities?.podman?.usable === true;
  const javaAvailable = capabilities?.java?.usable === true;
  const nextflowAvailable = capabilities?.nextflow?.usable === true;
  const condaAvailable =
    capabilities?.micromamba?.usable === true ||
    capabilities?.conda?.usable === true ||
    envStatus?.conda_runtime?.installed === true;

  const runtimeReadyDetected = isRuntimeReady(preflight, envStatus, resolvedRuntimeForInspection);
  const runtimeReady = preflight
    ? runtimeReadyDetected
    : loading
      ? Boolean(runtimeReadyOverride)
      : Boolean(
          runtimeReadyOverride ||
            (detectedResolvedRuntime?.hostKey === currentHostKey &&
              detectedResolvedRuntime?.verificationStatus === "verified" &&
              detectedResolvedRuntime?.nextflowPath) ||
            resolvedNextflowPath
        );

  const runtimeSummary = useMemo<RuntimeReadySummary | null>(() => {
    if (!runtimeReady) {
      return null;
    }
    const runtimeHome = "~/.h2ometa/runtime";
    return {
      selectedProfile:
        preflight?.recommended_profile_details?.profile_kind ||
        preflight?.recommended_profile ||
        detectedResolvedRuntime?.selectedProfile ||
        "personal_conda",
      runtimeHome,
      nextflowPath: detectedResolvedRuntime?.nextflowPath || `${runtimeHome}/bin/nextflow`,
      micromambaPath: `${runtimeHome}/bin/micromamba`,
      javaPath: detectedResolvedRuntime?.javaPath || (javaAvailable ? `${runtimeHome}/java/bin/java` : undefined),
    };
  }, [detectedResolvedRuntime, javaAvailable, preflight, runtimeReady]);

  useEffect(() => {
    setDetectedResolvedRuntime(resolvedRuntime ?? null);
  }, [resolvedRuntime]);

  const loadData = useCallback(async () => {
    if (!sshStatus?.connected) {
      return null;
    }
    setLoading(true);
    setError("");
    try {
      const inspection = await loadRuntimeInspection();
      const nextPreflight = inspection.preflight;
      const nextEnv = inspection.envStatus;
      const nextDecision = getRecommendedDecision(nextPreflight);
      const nextResolvedRuntime = toLocalResolvedRuntime(inspection.resolvedRuntime);
      const nextRuntimeReady = isRuntimeReady(nextPreflight, nextEnv, inspection.resolvedRuntime);
      setPreflight(nextPreflight);
      setEnvStatus(nextEnv);
      setDetectedResolvedRuntime(nextResolvedRuntime);
      setSelectedDecision(nextDecision);
      setCurrentStep(nextRuntimeReady ? 4 : 1);
      setSentRemediationKeys({});
      if (nextResolvedRuntime?.verificationStatus === "verified") {
        setResolvedNextflowPath(nextResolvedRuntime.nextflowPath || "");
        setResolvedJavaPath(nextResolvedRuntime.javaPath || "");
      }
      if (!nextRuntimeReady) {
        setResolvedNextflowPath("");
        setResolvedJavaPath("");
      }
      return inspection;
    } catch (nextError) {
      const detail = formatRuntimeInspectionError(nextError);
      setPreflight(null);
      setEnvStatus(null);
      setSelectedDecision(null);
      setCurrentStep(1);
      setError(`运行时检测失败：${detail}`);
      return null;
    } finally {
      setLoading(false);
    }
  }, [sshStatus?.connected]);

  useEffect(() => {
    if (!open || !sshStatus?.connected) {
      return;
    }
    void loadData();
  }, [loadData, open, sshStatus?.connected]);

  const beginBootstrap = useCallback(async () => {
    if (!preflight) {
      return;
    }
    const effectiveDecision = selectedDecision || getRecommendedDecision(preflight) || "fallback_conda";
    const blockReason = getBootstrapBlockReason(preflight, effectiveDecision);
    if (blockReason) {
      setError(blockReason);
      return;
    }
    setCurrentStep(3);
    setError("");
    setFlowNotice("请按顺序通过终端逐条发送修复命令；每发一步都要在终端确认输出，再点击“重新检测”完成复检。");
  }, [preflight, selectedDecision]);

  const syncPreparedState = useCallback(
    async (inspection: RuntimeInspection) => {
      const refreshedRuntime = inspection.preflight?.runtime_capabilities || {};
      const nextflowNowUsable = refreshedRuntime?.nextflow?.usable === true;
      const nextflowResolvedPath = String(refreshedRuntime?.nextflow?.path || inspection.resolvedRuntime?.nextflow_path || "").trim();
      const javaResolvedPath = String(refreshedRuntime?.java?.path || inspection.resolvedRuntime?.java_path || "").trim();
      if (!nextflowResolvedPath || !nextflowNowUsable) {
        return false;
      }
      const selectedProfile =
        inspection.preflight?.recommended_profile_details?.profile_kind ||
        inspection.preflight?.recommended_profile ||
        "personal_conda";
      await requestLocalApiJson("PUT", "/api/v1/runtime/resolved", {
        body: {
          host_key: currentHostKey,
          selected_profile: selectedProfile,
          resolved_at: new Date().toISOString(),
          verification_status: "verified",
          nextflow_path: nextflowResolvedPath,
          nextflow_command: String(refreshedRuntime?.nextflow?.command || inspection.resolvedRuntime?.nextflow_command || "").trim() || nextflowResolvedPath,
          nextflow_source: String(refreshedRuntime?.nextflow?.source || inspection.resolvedRuntime?.nextflow_source || "").trim(),
          nextflow_message: String(refreshedRuntime?.nextflow?.message || inspection.resolvedRuntime?.nextflow_message || "").trim() || "已检测到 Nextflow，可直接使用",
          java_path: javaResolvedPath,
          java_home: String(refreshedRuntime?.java?.home || inspection.resolvedRuntime?.java_home || "").trim(),
          java_message: String(refreshedRuntime?.java?.message || inspection.resolvedRuntime?.java_message || "").trim() || "已检测到 Java，可用于运行 Nextflow",
        },
      });
      setDetectedResolvedRuntime({
        hostKey: currentHostKey,
        nextflowPath: nextflowResolvedPath,
        javaPath: javaResolvedPath,
        selectedProfile,
        verificationStatus: "verified",
      });
      setResolvedNextflowPath(nextflowResolvedPath);
      setResolvedJavaPath(javaResolvedPath);
      setFlowNotice("");
      setCurrentStep(4);
      onPrepared?.({
        nextflowPath: nextflowResolvedPath,
        javaPath: javaResolvedPath,
        selectedProfile,
      });
      return true;
    },
    [currentHostKey, onPrepared]
  );

  const runRecheck = useCallback(async () => {
    setError("");
    const inspection = await loadData();
    if (!inspection) {
      return;
    }
    const ready = await syncPreparedState(inspection);
    if (!ready) {
      setCurrentStep(3);
      setFlowNotice("已完成重新检测。若终端中还有未执行的修复命令，请继续逐条发送；命令发送成功 ≠ 环境已修复成功。");
    }
  }, [loadData, syncPreparedState]);

  const sendRemediationCommand = useCallback(
    async (step: RemediationCommand) => {
      setError("");
      setFlowNotice("");
      if (!onSendTerminalCommand) {
        onOpenTerminal?.();
        setError("终端命令发送钩子不可用，请先打开终端后手动执行该命令。");
        return;
      }
      const sent = await onSendTerminalCommand(step.command);
      if (!sent) {
        setError("终端尚未就绪，无法发送修复命令。请先打开终端并确认 SSH 会话可输入。");
        return;
      }
      setSentRemediationKeys((current) => ({ ...current, [step.key]: true }));
      setCurrentStep(3);
      setFlowNotice(`已发送“${step.label}”。请先在终端确认输出，再点击“重新检测”验证修复是否真正生效。`);
    },
    [onOpenTerminal, onSendTerminalCommand]
  );

  const checklist = useMemo(() => buildChecklist(preflight, envStatus, detectedResolvedRuntime), [detectedResolvedRuntime, envStatus, preflight]);
  const checklistSections = useMemo(() => (preflight ? buildSections(checklist) : []), [checklist, preflight]);
  const bashPath = useMemo(() => getCheckItemValue(checklist, "bash", "未检测到可用 Bash"), [checklist]);
  const confirmationNextflowPath = useMemo(
    () => getCheckItemValue(checklist, "nextflow", detectedResolvedRuntime?.nextflowPath || resolvedNextflowPath || "未解析到可用 Nextflow"),
    [checklist, detectedResolvedRuntime?.nextflowPath, resolvedNextflowPath]
  );
  const confirmationJavaPath = useMemo(
    () => getCheckItemValue(checklist, "java", detectedResolvedRuntime?.javaPath || resolvedJavaPath || "未解析到可用 Java"),
    [checklist, detectedResolvedRuntime?.javaPath, resolvedJavaPath]
  );
  const remediationSections = useMemo(
    () => buildRemediationSections({ checklist, preflight, resolvedRuntime: detectedResolvedRuntime }),
    [checklist, detectedResolvedRuntime, preflight]
  );
  const serverLabel = sshStatus ? `${sshStatus.user}@${sshStatus.host}:${sshStatus.port}` : "未连接服务器";
  const bootstrapBlockReason = useMemo(() => getBootstrapBlockReason(preflight, selectedDecision), [preflight, selectedDecision]);
  const canAdvanceFromDetection = Boolean(preflight) && !loading;
  const recommendedExplanation = getRecommendedExplanation({ dockerUsable, podmanUsable, preflight });
  const statusLabel = loading ? "检测中" : error && !preflight ? "检测失败" : runtimeReady ? "Runtime Ready" : "Runtime Missing";
  const statusClassName = loading
    ? "border-slate-200 bg-slate-50 text-slate-500"
    : error && !preflight
      ? "border-red-100 bg-red-50 text-red-600"
      : runtimeReady
        ? "border-emerald-100 bg-emerald-50 text-emerald-600"
        : "border-amber-100 bg-amber-50 text-amber-600";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[760px] w-[960px] max-h-[calc(100vh-32px)] max-w-[calc(100vw-32px)] flex-col overflow-hidden border-slate-100 bg-white p-0 shadow-2xl">
        <div className="px-8 pt-8 pb-6">
          <DialogHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
            <div className="space-y-1">
              <DialogTitle className="text-xl font-semibold text-slate-950">运行时设置</DialogTitle>
              <DialogDescription className="font-mono text-sm text-slate-400">{serverLabel}</DialogDescription>
            </div>
            <span className={cn("rounded-full border px-3 py-1 text-xs", statusClassName)}>{statusLabel}</span>
          </DialogHeader>

          <div className="mt-10 flex items-center border-b border-slate-100 pb-6 text-sm">
            {["检测环境", "准备 Runtime", "完成"].map((step, index) => {
              const visualStep = currentStep === 4 ? 3 : currentStep === 3 ? 2 : 1;
              const isActive = visualStep === index + 1;
              const isDone = visualStep > index + 1;
              return (
                <div key={step} className="flex items-center">
                  <div
                    className={cn(
                      "flex items-center gap-2.5",
                      isActive ? "font-medium text-slate-950" : isDone ? "text-slate-900" : "text-slate-300"
                    )}
                  >
                    <Circle
                      className={cn(
                        "h-2 w-2",
                        isActive
                          ? "fill-blue-600 text-blue-600"
                          : isDone
                            ? "fill-slate-900 text-slate-900"
                            : "fill-slate-200 text-slate-200"
                      )}
                    />
                    <span>{step}</span>
                  </div>
                  {index < 2 ? <ArrowRight className="mx-4 h-4 w-4 text-slate-200" /> : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-8 pt-2 pb-8">
          {error && preflight ? (
            <div className="mb-6 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">{error}</div>
          ) : null}
          {currentStep === 1 ? (
            preflight ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">检测环境</h3>
                  <p className="text-sm leading-relaxed text-slate-500">
                    系统会先按 Bash → Java → Nextflow 的固定顺序自动检测，再根据可用 Docker / Podman 自动选择执行后端；Conda 仅作为可选 fallback，不会阻塞一键配置。
                  </p>
                </div>

                <div className="grid gap-4 rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                  <div className="space-y-1">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">一键配置确认</p>
                    <p className="text-sm font-medium text-slate-950">自动检测已完成，确认后将按推荐路径继续配置。</p>
                    <p className="text-xs leading-relaxed text-slate-500">
                      后续运行会优先复用已验证的固定路径，而不是依赖 PATH 或 shell 自动加载结果。
                    </p>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <RuntimePath label="Bash" value={bashPath} />
                    <RuntimePath label="Java" value={confirmationJavaPath} />
                    <RuntimePath label="Nextflow" value={confirmationNextflowPath} />
                    <RuntimePath
                      label="推荐 Profile"
                      value={preflight?.recommended_profile || detectedResolvedRuntime?.selectedProfile || "等待自动选择"}
                    />
                  </div>
                  <div className="rounded-lg border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs leading-relaxed text-blue-700">
                    Conda Runtime 只作为容器运行时缺失时的补位能力，不会阻塞 Docker / Podman 的主路径确认。
                  </div>
                </div>

                <div className="space-y-4">
                  {checklistSections.map((section) => (
                    <section key={section.key} className="border-t border-slate-100 pt-4 first:pt-0">
                      <div className="mb-2 flex items-center justify-between gap-4">
                        <div className="space-y-0.5">
                          <h4 className="text-sm font-medium text-slate-900">{section.title}</h4>
                          <p className="text-xs leading-relaxed text-slate-500">{section.description}</p>
                        </div>
                        <div className="flex items-center gap-2">
                          {hasSectionWarnings(section) ? (
                            <span className="rounded-full border border-amber-100 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                              需关注
                            </span>
                          ) : null}
                          <span className="text-[11px] text-slate-400">{section.items.length} 项</span>
                        </div>
                      </div>

                      <div className="space-y-0">
                        {section.items.map((item) => {
                          const presentation = getStatusPresentation(item);
                          return (
                            <div
                              key={item.key}
                              className="flex items-start justify-between gap-4 border-b border-slate-100 py-3 last:border-b-0"
                            >
                              <div className="min-w-0 space-y-1">
                                <div className="flex items-center gap-2">
                                  <p className="text-sm font-medium text-slate-900">{item.label}</p>
                                  <span
                                    className={cn(
                                      "inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium",
                                      presentation.badgeClassName
                                    )}
                                  >
                                    {presentation.label}
                                  </span>
                                </div>
                                <p className="text-xs leading-relaxed text-slate-500">{item.message}</p>
                              </div>
                              <div className="shrink-0 text-right">
                                <p className="font-mono text-xs text-slate-700">{item.value}</p>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex min-h-[360px] items-center justify-center">
                <div className="w-full max-w-xl rounded-2xl border border-red-100 bg-red-50/70 p-6">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
                    <div className="space-y-2">
                      <h3 className="text-sm font-semibold text-red-700">运行时检测失败</h3>
                      <p className="text-sm leading-relaxed text-red-600">
                        当前无法获取服务器的真实检测结果，因此不会显示任何原型占位数据。请检查后端服务和 SSH 会话后重试。
                      </p>
                      {error ? <p className="font-mono text-xs text-red-500">{error}</p> : null}
                    </div>
                  </div>
                </div>
              </div>
            )
          ) : null}

          {currentStep === 3 ? (
            <div className="space-y-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">准备 Runtime</h3>
              {flowNotice ? (
                <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm text-blue-700">{flowNotice}</div>
              ) : null}
              {bootstrapBlockReason ? (
                <div className="rounded-xl border border-amber-100 bg-amber-50/70 px-4 py-3 text-sm text-amber-700">
                  {bootstrapBlockReason}
                </div>
              ) : null}
              <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm text-blue-700">
                命令发送成功 ≠ 修复成功。所有 Java / Nextflow / Docker 修复都必须通过终端逐条发送，发送后请先在终端确认输出，再点击“重新检测”完成复检。
              </div>
              <div className="rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                <p className="text-sm text-slate-700">
                  自动检测确认当前推荐使用 <strong>{preflight?.recommended_profile || "personal_conda"}</strong>。
                </p>
                <p className="mt-2 text-xs leading-relaxed text-slate-500">{recommendedExplanation}</p>
              </div>
              <div className="space-y-4">
                {remediationSections.map((section) => {
                  const badge = remediationBadge(section);
                  return (
                    <section key={section.key} className="rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <h4 className="text-sm font-semibold text-slate-900">{section.title}</h4>
                          <p className="mt-1 text-xs leading-relaxed text-slate-500">{section.summary}</p>
                        </div>
                        <span className={cn("rounded-full border px-2 py-0.5 text-[11px] font-medium", badge.className)}>{badge.label}</span>
                      </div>
                      {section.commands.length > 0 ? (
                        <div className="mt-4 space-y-3">
                          {section.commands.map((step, index) => {
                            const sent = sentRemediationKeys[step.key] === true;
                            return (
                              <div key={step.key} className="rounded-lg border border-slate-100 px-4 py-3">
                                <div className="flex items-start justify-between gap-3">
                                  <div className="space-y-1">
                                    <p className="text-sm font-medium text-slate-900">
                                      {index + 1}. {step.label}
                                    </p>
                                    <p className="text-xs leading-relaxed text-slate-500">{step.description}</p>
                                  </div>
                                  <Button
                                    variant={sent ? "outline" : "default"}
                                    className={cn("shrink-0", sent ? "border-slate-200 text-slate-600" : "bg-slate-950 text-white hover:bg-slate-800")}
                                    onClick={() => void sendRemediationCommand(step)}
                                  >
                                    {sent ? "再次发送" : "发送到终端"}
                                  </Button>
                                </div>
                                <pre className="mt-3 overflow-auto rounded-md bg-slate-950 px-3 py-2 font-mono text-[11px] text-slate-100">
                                  {step.command}
                                </pre>
                                <p className="mt-2 text-[11px] text-slate-500">
                                  {sent ? "状态：命令已发送，待终端确认与重新检测。" : "状态：尚未发送。"}
                                </p>
                              </div>
                            );
                          })}
                        </div>
                      ) : null}
                    </section>
                  );
                })}
              </div>
            </div>
          ) : null}

          {currentStep === 4 ? (
            <div className="space-y-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">确认当前运行时配置</h3>
              <div className="grid gap-4 rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
                <div>
                  <p className="text-sm font-semibold text-slate-950">当前 Profile</p>
                  <p className="mt-1 font-mono text-sm text-slate-600">{runtimeSummary?.selectedProfile || "personal_conda"}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <RuntimePath label="Bash" value={bashPath} />
                  <RuntimePath label="Runtime Home" value={runtimeSummary?.runtimeHome || "~/.h2ometa/runtime"} />
                  <RuntimePath label="Nextflow" value={confirmationNextflowPath || runtimeSummary?.nextflowPath || "未解析到可用 Nextflow"} />
                  <RuntimePath label="Micromamba" value={runtimeSummary?.micromambaPath || "~/.h2ometa/runtime/bin/micromamba"} />
                  <RuntimePath label="Java" value={confirmationJavaPath || runtimeSummary?.javaPath || "使用系统 Java"} />
                </div>
                <div className="rounded-lg border border-emerald-100 bg-emerald-50/70 px-4 py-3 text-xs leading-relaxed text-emerald-700">
                  后续运行将优先使用这组已验证的 Bash / Java / Nextflow 固定路径，不再依赖 PATH 漂移或 Conda 自动激活。
                </div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-8 py-5">
          <Button variant="ghost" className="px-0 text-slate-400 hover:bg-transparent hover:text-slate-900" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <div className="flex gap-3">
            {currentStep === 3 ? (
              <Button
                variant="outline"
                className="rounded-lg border-slate-200 text-slate-700"
                onClick={() => onOpenTerminal?.()}
              >
                打开终端修复
              </Button>
            ) : null}
            {currentStep === 1 ? (
              <Button variant="outline" className="rounded-lg border-slate-200 text-slate-700" onClick={() => void loadData()}>
                <RefreshCw className="mr-2 h-4 w-4" /> 重新检测
              </Button>
            ) : null}
            {currentStep === 1 ? (
              <Button
                className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800"
                disabled={!canAdvanceFromDetection || runtimeReady}
                onClick={() => void beginBootstrap()}
              >
                一键配置 Runtime
              </Button>
            ) : null}
            {currentStep === 3 ? (
              <Button
                variant="outline"
                className="rounded-lg border-slate-200 text-slate-700"
                onClick={() => void runRecheck()}
              >
                <RefreshCw className="mr-2 h-4 w-4" /> 重新检测
              </Button>
            ) : null}
            {currentStep === 4 ? (
              <Button className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800" onClick={() => onOpenChange(false)}>
                完成
              </Button>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RuntimePath({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-100 px-4 py-3">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="mt-1 font-mono text-sm text-slate-700">{value}</p>
    </div>
  );
}
