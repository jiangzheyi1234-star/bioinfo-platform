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
  startRemoteEnvInstall,
  type EnvStatusPayload,
  type PreflightPayload,
} from "@/app/components/runtime-inspection";
import { requestLocalApiJson } from "@/app/lib/local-api-client";
import {
  buildRuntimePrepareView,
  type BootstrapStep,
  type InstallSnapshot,
  type RuntimeDecisionOption,
} from "@/app/components/runtime-prepare-progress";

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

function buildChecklist(preflight: PreflightPayload | null, envStatus: EnvStatusPayload | null): RuntimeCheckItem[] {
  if (!preflight) {
    return [];
  }

  const checksByKey = new Map((preflight.checks || []).map((item) => [item.key, item]));
  const runtime = preflight.runtime_capabilities || {};
  const condaInstalled = envStatus?.conda_runtime?.installed === true;
  const condaExecutable = envStatus?.conda_runtime?.conda_executable || "";

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
    makeRuntimeItem({
      key: "java",
      fallbackLabel: "Java 17+",
      fallbackStatus: runtime.java?.usable ? "ready" : runtime.java?.available ? "blocked" : "missing",
      fallbackValue: runtime.java?.version || (runtime.java?.available ? "installed" : "missing"),
      fallbackMessage: runtime.java?.usable
        ? "已检测到 Java，可用于运行 Nextflow"
        : runtime.java?.message
          ? runtime.java.message
          : runtime.java?.available
            ? "已检测到 Java，但当前不可正常调用"
            : "未检测到 Java，无法运行 Nextflow",
    }),
    makeRuntimeItem({
      key: "nextflow",
      fallbackLabel: "Nextflow",
      fallbackStatus: runtime.nextflow?.usable ? "ready" : runtime.nextflow?.available ? "blocked" : "missing",
      fallbackValue: runtime.nextflow?.version || (runtime.nextflow?.available ? "installed" : "missing"),
      fallbackMessage: runtime.nextflow?.usable
        ? "已检测到 Nextflow"
        : runtime.nextflow?.message
          ? runtime.nextflow.message
          : runtime.nextflow?.available
            ? "已检测到 Nextflow，但当前不可正常调用"
            : "未检测到 Nextflow",
    }),
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
      key: "core-runtime",
      title: "基础运行时",
      description: "决定这台服务器能否先跑通 Nextflow 与 Conda 路线。",
      keys: ["java", "nextflow", "micromamba", "conda"],
    },
    {
      key: "container-runtime",
      title: "容器运行时",
      description: "用于决定后续是否优先走 Docker / Podman 容器模式。",
      keys: ["docker", "podman", "apptainer"],
    },
    {
      key: "server-baseline",
      title: "服务器基线",
      description: "影响下载、目录创建与后续运行目录初始化。",
      keys: ["home_writable", "disk", "bash", "downloader", "sha256sum", "screen"],
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
    return "请先完成一次真实检测，再决定走容器模式还是 Conda Runtime。";
  }
  if (args.dockerUsable) {
    return "检测到 Docker，可优先使用容器模式。";
  }
  if (args.podmanUsable) {
    return "未检测到 Docker，但 Podman 可用，建议使用容器模式。";
  }
  return "未检测到可用容器运行时，建议继续使用 Conda Runtime。";
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
}: PrepareServerWizardProps) {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [preflight, setPreflight] = useState<PreflightPayload | null>(null);
  const [envStatus, setEnvStatus] = useState<EnvStatusPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedDecision, setSelectedDecision] = useState<RuntimeDecisionOption | null>(null);
  const [installSnapshot, setInstallSnapshot] = useState<InstallSnapshot | null>(null);
  const [installJobId, setInstallJobId] = useState("");
  const [installTarget, setInstallTarget] = useState<InstallTarget>("");
  const [installRunning, setInstallRunning] = useState(false);
  const [flowNotice, setFlowNotice] = useState("");
  const [resolvedNextflowPath, setResolvedNextflowPath] = useState("");
  const [resolvedJavaPath, setResolvedJavaPath] = useState("");
  const currentHostKey = runtimeHostKey(sshStatus);

  const capabilities = preflight?.runtime_capabilities;
  const dockerUsable = capabilities?.docker?.usable === true;
  const podmanUsable = capabilities?.podman?.usable === true;
  const javaAvailable = capabilities?.java?.usable === true;
  const nextflowAvailable = capabilities?.nextflow?.usable === true;
  const condaAvailable =
    capabilities?.micromamba?.usable === true ||
    capabilities?.conda?.usable === true ||
    envStatus?.conda_runtime?.installed === true;

  const runtimeReadyDetected = isRuntimeReady(preflight, envStatus);
  const runtimeReady = preflight
    ? runtimeReadyDetected
    : loading
      ? Boolean(runtimeReadyOverride)
      : Boolean(
          runtimeReadyOverride ||
            (resolvedRuntime?.hostKey === currentHostKey &&
              resolvedRuntime?.verificationStatus === "verified" &&
              resolvedRuntime?.nextflowPath) ||
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
        resolvedRuntime?.selectedProfile ||
        "personal_conda",
      runtimeHome,
      nextflowPath: resolvedRuntime?.nextflowPath || `${runtimeHome}/bin/nextflow`,
      micromambaPath: `${runtimeHome}/bin/micromamba`,
      javaPath: resolvedRuntime?.javaPath || (javaAvailable ? `${runtimeHome}/java/bin/java` : undefined),
    };
  }, [javaAvailable, preflight, resolvedRuntime, runtimeReady]);

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
      const nextRuntimeReady = isRuntimeReady(nextPreflight, nextEnv);
      setPreflight(nextPreflight);
      setEnvStatus(nextEnv);
      setSelectedDecision(nextDecision);
      setCurrentStep(nextRuntimeReady ? 4 : 1);
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

  useEffect(() => {
    if (!installJobId) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await requestLocalApiJson("GET", `/api/v1/ssh/env/install/${encodeURIComponent(installJobId)}`);
        const snapshot = (data?.item || null) as InstallSnapshot | null;
        if (!cancelled && snapshot) {
          setInstallSnapshot(snapshot);
          if (snapshot.done) {
            setInstallRunning(false);
            if (snapshot.ok) {
              const refreshed = await loadData();
              const refreshedRuntime = refreshed?.preflight?.runtime_capabilities || {};
              if (installTarget === "docker_runtime") {
                const dockerNowUsable = refreshedRuntime?.docker?.usable === true;
                setSelectedDecision(dockerNowUsable ? "use_docker" : "fallback_conda");
                setCurrentStep(2);
                setFlowNotice(
                  dockerNowUsable
                    ? "Docker 协助安装已完成，下一步可以直接继续准备 Workflow Runtime。"
                    : "Docker 已安装，但当前 SSH 会话可能尚未获得 docker 组权限；请断开并重新连接后重新检测。"
                );
              } else {
                const nextflowNowUsable = refreshedRuntime?.nextflow?.usable === true;
                const nextflowResolvedPath =
                  String(refreshedRuntime?.nextflow?.path || "").trim() || extractLogField(snapshot.log_text || "", "NEXTFLOW_PATH");
                const javaResolvedPath =
                  String(refreshedRuntime?.java?.path || "").trim() || extractLogField(snapshot.log_text || "", "JAVA_PATH");
                if (nextflowResolvedPath && (nextflowNowUsable || snapshot.ok)) {
                  setResolvedNextflowPath(nextflowResolvedPath);
                  setResolvedJavaPath(javaResolvedPath);
                  const selectedProfile =
                    refreshed?.preflight?.recommended_profile_details?.profile_kind ||
                    refreshed?.preflight?.recommended_profile ||
                    "personal_conda";
                  await requestLocalApiJson("PUT", "/api/v1/runtime/resolved", {
                    body: {
                      host_key: currentHostKey,
                      selected_profile: selectedProfile,
                      resolved_at: new Date().toISOString(),
                      verification_status: "verified",
                      nextflow_path: nextflowResolvedPath,
                      nextflow_command:
                        String(refreshedRuntime?.nextflow?.command || "").trim() || nextflowResolvedPath,
                      nextflow_source: String(refreshedRuntime?.nextflow?.source || "").trim(),
                      nextflow_message:
                        String(refreshedRuntime?.nextflow?.message || "").trim() || "已检测到 Nextflow，可直接使用",
                      java_path: javaResolvedPath,
                      java_home: String(refreshedRuntime?.java?.home || "").trim(),
                      java_message:
                        String(refreshedRuntime?.java?.message || "").trim() || "已检测到 Java，可用于运行 Nextflow",
                    },
                  });
                  setFlowNotice("");
                  setCurrentStep(4);
                  onPrepared?.({
                    nextflowPath: nextflowResolvedPath,
                    javaPath: javaResolvedPath,
                    selectedProfile,
                  });
                } else {
                  setCurrentStep(3);
                  setError(
                    String(refreshedRuntime?.nextflow?.message || "Runtime 准备已完成，但重新检测时仍未解析到可用 Nextflow。请重新检测或检查 SSH 运行环境。")
                  );
                }
              }
            } else {
              setError(snapshot.message || "后台安装失败，请查看日志。");
            }
            return;
          }
        }
      } catch (nextError) {
        if (!cancelled) {
          setInstallRunning(false);
          setError(formatApiFetchError(nextError, "安装状态查询失败。"));
        }
        return;
      }
      if (!cancelled) {
        window.setTimeout(poll, 1000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [installJobId, loadData, onPrepared]);

  const beginBootstrap = useCallback(async () => {
    if (!preflight) {
      return;
    }
    const effectiveDecision = selectedDecision || recommendedDecision || "fallback_conda";
    const blockReason = getBootstrapBlockReason(preflight, effectiveDecision);
    if (blockReason) {
      setError(blockReason);
      return;
    }

    setInstallRunning(true);
    setCurrentStep(3);
    setError("");
    setFlowNotice("");
    setInstallSnapshot(null);
    try {
      const target = effectiveDecision === "assistant_install_docker" ? "docker_runtime" : "workflow_runtime";
      setInstallTarget(target);
      const profileKind =
        effectiveDecision === "use_docker"
          ? "personal_docker"
          : effectiveDecision === "use_podman"
            ? "personal_podman"
            : "personal_conda";
      const data = await startRemoteEnvInstall(
        target === "docker_runtime"
          ? { target }
          : { target, profile_kind: profileKind }
      );
      const jobId = String(data?.item?.job_id || "");
      setInstallJobId(jobId);
    } catch (nextError) {
      setInstallRunning(false);
      setError(formatApiFetchError(nextError, "无法启动 Runtime 准备流程。"));
    }
  }, [preflight, recommendedDecision, selectedDecision]);

  const checklist = useMemo(() => buildChecklist(preflight, envStatus), [envStatus, preflight]);
  const checklistSections = useMemo(() => (preflight ? buildSections(checklist) : []), [checklist, preflight]);
  const runtimePrepareView = useMemo(
    () =>
      buildRuntimePrepareView({
        selectedDecision,
        installTarget,
        snapshot: installSnapshot,
        installRunning,
      }),
    [installRunning, installSnapshot, installTarget, selectedDecision]
  );
  const bootstrapSteps = runtimePrepareView.steps;
  const serverLabel = sshStatus ? `${sshStatus.user}@${sshStatus.host}:${sshStatus.port}` : "未连接服务器";
  const showDockerChoices = Boolean(preflight) && !dockerUsable && !podmanUsable;
  const bootstrapBlockReason = useMemo(() => getBootstrapBlockReason(preflight, selectedDecision), [preflight, selectedDecision]);
  const canRunBootstrap = selectedDecision !== null && selectedDecision !== "self_install_docker" && !bootstrapBlockReason;
  const canAdvanceFromDetection = Boolean(preflight) && !loading;
  const recommendedDecision = preflight ? getRecommendedDecision(preflight) : null;
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
                    先确认这台服务器是否具备运行条件，再决定是否继续走 Docker / Podman 容器模式，还是直接进入 Conda Runtime。
                  </p>
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
              <div className="rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                <p className="text-sm text-slate-700">
                  当前推荐使用 <strong>{preflight?.recommended_profile || "personal_conda"}</strong>。
                </p>
                <p className="mt-2 text-xs leading-relaxed text-slate-500">{recommendedExplanation}</p>
              </div>
              <div className="space-y-4">
                {bootstrapSteps.map((step) => (
                  <div key={step.key} className="flex items-center justify-between rounded-lg border border-slate-100 px-4 py-3">
                    <div className="flex items-center gap-3">
                      {step.status === "done" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      ) : step.status === "running" ? (
                        <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
                      ) : step.status === "failed" ? (
                        <AlertTriangle className="h-4 w-4 text-red-500" />
                      ) : (
                        <Circle className="h-4 w-4 text-slate-300" />
                      )}
                      <div>
                        <p className="text-sm font-medium text-slate-900">{step.label}</p>
                        {step.message ? <p className="text-xs text-slate-500">{step.message}</p> : null}
                      </div>
                    </div>
                    <span className="text-xs text-slate-400">{step.status}</span>
                  </div>
                ))}
              </div>

              <div className="h-40 overflow-auto rounded-xl border border-slate-100 bg-slate-950 p-4 font-mono text-xs text-slate-200">
                <pre>{installSnapshot?.log_text || runtimePrepareView.emptyLogText}</pre>
              </div>
            </div>
          ) : null}

          {currentStep === 4 ? (
            <div className="space-y-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">服务器已就绪</h3>
              <div className="grid gap-4 rounded-xl border border-slate-100 bg-white p-6 shadow-sm">
                <div>
                  <p className="text-sm font-semibold text-slate-950">当前 Profile</p>
                  <p className="mt-1 font-mono text-sm text-slate-600">{runtimeSummary?.selectedProfile || "personal_conda"}</p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <RuntimePath label="Runtime Home" value={runtimeSummary?.runtimeHome || "~/.h2ometa/runtime"} />
                  <RuntimePath label="Nextflow" value={capabilities?.nextflow?.path || resolvedNextflowPath || runtimeSummary?.nextflowPath || "未解析到可用 Nextflow"} />
                  <RuntimePath label="Micromamba" value={runtimeSummary?.micromambaPath || "~/.h2ometa/runtime/bin/micromamba"} />
                  <RuntimePath label="Java" value={capabilities?.java?.path || resolvedJavaPath || runtimeSummary?.javaPath || "使用系统 Java"} />
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
                className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800"
                disabled={installRunning || !canRunBootstrap}
                onClick={() => void beginBootstrap()}
              >
                {installRunning ? "配置中..." : "重新配置 Runtime"}
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
