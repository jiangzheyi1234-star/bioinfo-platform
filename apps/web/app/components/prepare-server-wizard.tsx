"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Circle, Info, Loader2, PackageSearch, RefreshCw, Server } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

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

type RuntimeDecisionOption =
  | "use_docker"
  | "use_podman"
  | "self_install_docker"
  | "assistant_install_docker"
  | "fallback_conda";

type BootstrapStep = {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "failed";
  message?: string;
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

type RuntimeCapabilities = {
  java?: { available?: boolean; usable?: boolean; version?: string };
  nextflow?: { available?: boolean; usable?: boolean; version?: string };
  docker?: { available?: boolean; usable?: boolean };
  podman?: { available?: boolean; usable?: boolean };
  apptainer?: { available?: boolean; usable?: boolean };
  micromamba?: { available?: boolean; usable?: boolean };
  conda?: { available?: boolean; usable?: boolean };
};

type PreflightPayload = {
  ok: boolean;
  checks: Array<{
    key: string;
    label: string;
    status: "ok" | "warn" | "fail";
    value: string;
    message: string;
  }>;
  failures: string[];
  warnings: string[];
  recommended_profile: string;
  recommended_profile_details?: {
    profile_id?: string;
    profile_kind?: string;
  };
  supported_profile_kinds: string[];
  runtime_capabilities?: RuntimeCapabilities;
};

type EnvStatusPayload = {
  miniforge?: {
    installed?: boolean;
    conda_executable?: string;
  };
};

type InstallSnapshot = {
  job_id: string;
  status: string;
  done: boolean;
  ok: boolean;
  message: string;
  log_text: string;
};

type InstallTarget = "workflow_runtime" | "docker_runtime" | "";

type PrepareServerWizardProps = {
  open: boolean;
  mode: "wizard" | "settings";
  sshStatus: SSHStatus | null;
  runtimeReady?: boolean;
  onOpenChange: (open: boolean) => void;
  onPrepared?: () => void;
};

const FALLBACK_PREFLIGHT: PreflightPayload = {
  ok: false,
  checks: [
    { key: "bash", label: "bash", status: "ok", value: "unknown", message: "后端检测接口未接通，当前显示为 UI 原型占位。" },
    { key: "home_writable", label: "HOME 可写", status: "warn", value: "unknown", message: "等待后端接入后返回真实结果。" },
    { key: "disk", label: "磁盘空间", status: "warn", value: "unknown", message: "等待后端接入后返回真实结果。" },
  ],
  failures: [],
  warnings: ["检测环境接口尚未接通，当前步骤先以 UI 原型模式展示。"],
  recommended_profile: "personal_conda",
  recommended_profile_details: {
    profile_id: "personal_conda",
    profile_kind: "personal_conda",
  },
  supported_profile_kinds: ["personal_docker", "personal_podman", "personal_conda"],
  runtime_capabilities: {
    java: { available: false },
    nextflow: { available: false },
    docker: { available: false },
    podman: { available: false },
    apptainer: { available: false },
    micromamba: { available: false },
    conda: { available: false },
  },
};

const FALLBACK_ENV_STATUS: EnvStatusPayload = {
  miniforge: {
    installed: false,
    conda_executable: "",
  },
};

function apiBase(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";
  return raw.trim().replace(/\/+$/, "");
}

async function readJsonOrThrow(resp: Response) {
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(detail || `HTTP ${resp.status}`);
  }
  return payload;
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
  const condaInstalled = envStatus?.miniforge?.installed === true;
  const condaExecutable = envStatus?.miniforge?.conda_executable || "";

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

function buildBootstrapSteps(snapshot: InstallSnapshot | null): BootstrapStep[] {
  if (!snapshot) {
    return [
      { key: "java", label: "准备 Java", status: "pending" },
      { key: "nextflow", label: "安装 Nextflow", status: "pending" },
      { key: "micromamba", label: "安装 Micromamba", status: "pending" },
      { key: "runtime_dirs", label: "创建运行目录", status: "pending" },
      { key: "verification", label: "验证安装", status: "pending" },
    ];
  }
  const stage = snapshot.status;
  const done = stage === "done";
  const failed = stage === "failed";
  if (done || failed) {
    return [
      { key: "java", label: "准备 Java", status: done ? "done" : "failed" },
      { key: "nextflow", label: "安装 Nextflow", status: done ? "done" : "failed" },
      { key: "micromamba", label: "安装 Micromamba", status: done ? "done" : "failed" },
      { key: "runtime_dirs", label: "创建运行目录", status: done ? "done" : "failed" },
      { key: "verification", label: "验证安装", status: done ? "done" : "failed", message: snapshot.message || undefined },
    ];
  }
  return [
    { key: "java", label: "准备 Java", status: "done" },
    { key: "nextflow", label: "安装 Nextflow", status: "running" },
    { key: "micromamba", label: "安装 Micromamba", status: "running" },
    { key: "runtime_dirs", label: "创建运行目录", status: "running" },
    { key: "verification", label: "验证安装", status: "pending" },
  ];
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

function summarizeChecks(items: RuntimeCheckItem[]): { ready: number; warn: number; missing: number; blocked: number } {
  return items.reduce(
    (acc, item) => {
      acc[item.status] += 1;
      return acc;
    },
    { ready: 0, warn: 0, missing: 0, blocked: 0 }
  );
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
      items: items.filter((item) => group.keys.includes(item.key)),
    }))
    .filter((section) => section.items.length > 0);
}

function getRecommendedExplanation(args: {
  dockerUsable: boolean;
  podmanUsable: boolean;
  preflight: PreflightPayload | null;
}): string {
  if (args.dockerUsable) {
    return "检测到 Docker，可优先使用容器模式。";
  }
  if (args.podmanUsable) {
    return "未检测到 Docker，但 Podman 可用，建议使用容器模式。";
  }
  return "未检测到可用容器运行时，建议继续使用 Conda Runtime。";
}

export function PrepareServerWizard({
  open,
  mode,
  sshStatus,
  runtimeReady: runtimeReadyOverride,
  onOpenChange,
  onPrepared,
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
  const [prototypeMode, setPrototypeMode] = useState(false);
  const [flowNotice, setFlowNotice] = useState("");

  const capabilities = preflight?.runtime_capabilities;
  const dockerAvailable = capabilities?.docker?.available === true;
  const podmanAvailable = capabilities?.podman?.available === true;
  const dockerUsable = capabilities?.docker?.usable === true;
  const podmanUsable = capabilities?.podman?.usable === true;
  const javaAvailable = capabilities?.java?.usable === true;
  const nextflowAvailable = capabilities?.nextflow?.usable === true;
  const condaAvailable =
    capabilities?.micromamba?.usable === true ||
    capabilities?.conda?.usable === true ||
    envStatus?.miniforge?.installed === true;

  const runtimeReadyDetected = Boolean(javaAvailable && nextflowAvailable && (dockerUsable || podmanUsable || condaAvailable));
  const runtimeReady = runtimeReadyOverride ?? runtimeReadyDetected;

  const runtimeSummary = useMemo<RuntimeReadySummary | null>(() => {
    if (!runtimeReady || !preflight) {
      return null;
    }
    const runtimeHome = "~/.h2ometa/runtime";
    return {
      selectedProfile:
        preflight.recommended_profile_details?.profile_kind ||
        preflight.recommended_profile ||
        "personal_conda",
      runtimeHome,
      nextflowPath: `${runtimeHome}/bin/nextflow`,
      micromambaPath: `${runtimeHome}/bin/micromamba`,
      javaPath: javaAvailable ? `${runtimeHome}/java/bin/java` : undefined,
    };
  }, [javaAvailable, preflight, runtimeReady]);

  const loadData = useCallback(async () => {
    if (!sshStatus?.connected) {
      return null;
    }
    setLoading(true);
    setError("");
    setPrototypeMode(false);
    try {
      const [preflightResp, envResp] = await Promise.all([
        fetch(`${apiBase()}/api/v1/ssh/preflight`, { method: "POST" }),
        fetch(`${apiBase()}/api/v1/ssh/env/status`, { cache: "no-store" }),
      ]);
      const [preflightData, envData] = await Promise.all([readJsonOrThrow(preflightResp), readJsonOrThrow(envResp)]);
      const nextPreflight = (preflightData?.item || null) as PreflightPayload | null;
      const nextEnv = (envData?.item || null) as EnvStatusPayload | null;
      setPreflight(nextPreflight);
      setEnvStatus(nextEnv);
      const nextRuntime = nextPreflight?.runtime_capabilities || {};
      const nextDockerUsable = nextRuntime?.docker?.usable === true;
      const nextPodmanUsable = nextRuntime?.podman?.usable === true;
      if (!selectedDecision) {
        if (nextPreflight?.recommended_profile === "personal_docker" && nextDockerUsable) {
          setSelectedDecision("use_docker");
        } else if (nextPreflight?.recommended_profile === "personal_podman" && nextPodmanUsable) {
          setSelectedDecision("use_podman");
        } else {
          setSelectedDecision("self_install_docker");
        }
      }
      setCurrentStep(runtimeReady ? 4 : 1);
      return { preflight: nextPreflight, envStatus: nextEnv, prototypeMode: false };
    } catch (nextError) {
      setPreflight(FALLBACK_PREFLIGHT);
      setEnvStatus(FALLBACK_ENV_STATUS);
      setSelectedDecision((current) => current || "self_install_docker");
      setCurrentStep(1);
      setPrototypeMode(true);
      setError("");
      console.warn("PrepareServerWizard backend unavailable, falling back to prototype mode:", nextError);
      return { preflight: FALLBACK_PREFLIGHT, envStatus: FALLBACK_ENV_STATUS, prototypeMode: true };
    } finally {
      setLoading(false);
    }
  }, [runtimeReady, selectedDecision, sshStatus?.connected]);

  useEffect(() => {
    if (!open || !sshStatus?.connected) {
      return;
    }
    void loadData();
  }, [loadData, open, sshStatus?.connected]);

  useEffect(() => {
    if (!open || !installJobId) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install/${encodeURIComponent(installJobId)}`);
        const data = await readJsonOrThrow(resp);
        const snapshot = (data?.item || null) as InstallSnapshot | null;
        if (!cancelled && snapshot) {
          setInstallSnapshot(snapshot);
          if (snapshot.done) {
            setInstallRunning(false);
            if (snapshot.ok) {
              const refreshed = await loadData();
              if (installTarget === "docker_runtime") {
                const refreshedRuntime = refreshed?.preflight?.runtime_capabilities || {};
                const dockerNowUsable = refreshedRuntime?.docker?.usable === true;
                setSelectedDecision(dockerNowUsable ? "use_docker" : "self_install_docker");
                setCurrentStep(2);
                setFlowNotice(
                  dockerNowUsable
                    ? "Docker 协助安装已完成，下一步可以直接继续准备 Workflow Runtime。"
                    : "Docker 已安装，但当前 SSH 会话可能尚未获得 docker 组权限；请断开并重新连接后重新检查。"
                );
              } else {
                setFlowNotice("");
                setCurrentStep(4);
                onPrepared?.();
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
          setError(nextError instanceof Error ? nextError.message : String(nextError));
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
  }, [installJobId, loadData, onPrepared, open]);

  const beginBootstrap = useCallback(async () => {
    if (!preflight) {
      return;
    }
    if (selectedDecision === "self_install_docker") {
      return;
    }

    setInstallRunning(true);
    setCurrentStep(3);
    setError("");
    setFlowNotice("");
    setInstallSnapshot(null);
    try {
      const target = selectedDecision === "assistant_install_docker" ? "docker_runtime" : "workflow_runtime";
      setInstallTarget(target);
      const profileKind =
        selectedDecision === "use_docker"
          ? "personal_docker"
          : selectedDecision === "use_podman"
            ? "personal_podman"
            : "personal_conda";
      const resp = await fetch(`${apiBase()}/api/v1/ssh/env/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          target === "docker_runtime"
            ? { target }
            : { target, profile_kind: profileKind }
        ),
      });
      const data = await readJsonOrThrow(resp);
      const jobId = String(data?.item?.job_id || "");
      setInstallJobId(jobId);
    } catch (nextError) {
      setInstallRunning(false);
      setError(nextError instanceof Error ? nextError.message : String(nextError));
    }
  }, [preflight, selectedDecision]);

  const checklist = useMemo(() => buildChecklist(preflight, envStatus), [envStatus, preflight]);
  const checklistSections = useMemo(() => buildSections(checklist), [checklist]);
  const checklistSummary = useMemo(() => summarizeChecks(checklist), [checklist]);
  const bootstrapSteps = useMemo(() => {
    if (installTarget !== "docker_runtime") {
      return buildBootstrapSteps(installSnapshot);
    }
    if (!installSnapshot) {
      return [
        { key: "sudo", label: "校验 sudo / root 权限", status: "pending" },
        { key: "download", label: "下载 Docker 安装脚本", status: "pending" },
        { key: "install", label: "安装 Docker", status: "pending" },
        { key: "service", label: "启动 Docker 服务", status: "pending" },
        { key: "verify", label: "验证 Docker 并提示重新检查", status: "pending" },
      ];
    }
    if (installSnapshot.status === "done" || installSnapshot.status === "failed") {
      const terminalStatus = installSnapshot.status === "done" ? "done" : "failed";
      return [
        { key: "sudo", label: "校验 sudo / root 权限", status: terminalStatus },
        { key: "download", label: "下载 Docker 安装脚本", status: terminalStatus },
        { key: "install", label: "安装 Docker", status: terminalStatus },
        { key: "service", label: "启动 Docker 服务", status: terminalStatus },
        { key: "verify", label: "验证 Docker 并提示重新检查", status: terminalStatus, message: installSnapshot.message || undefined },
      ];
    }
    return [
      { key: "sudo", label: "校验 sudo / root 权限", status: "running" },
      { key: "download", label: "下载 Docker 安装脚本", status: "running" },
      { key: "install", label: "安装 Docker", status: "running" },
      { key: "service", label: "启动 Docker 服务", status: "running" },
      { key: "verify", label: "验证 Docker 并提示重新检查", status: "pending" },
    ];
  }, [installSnapshot, installTarget]);
  const serverLabel = sshStatus ? `${sshStatus.user}@${sshStatus.host}:${sshStatus.port}` : "未连接服务器";
  const showDockerChoices = !dockerUsable && !podmanUsable;
  const canRunBootstrap = !prototypeMode && selectedDecision !== "self_install_docker";
  const recommendedExplanation = getRecommendedExplanation({ dockerUsable, podmanUsable, preflight });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-4xl overflow-hidden border-slate-100 bg-white p-0 shadow-2xl">
        <div className="px-8 pt-8 pb-6">
          <DialogHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
            <div className="space-y-1">
              <DialogTitle className="text-xl font-semibold text-slate-950">
                {mode === "settings" ? "运行时设置" : "准备服务器"}
              </DialogTitle>
              <DialogDescription className="font-mono text-sm text-slate-400">{serverLabel}</DialogDescription>
            </div>
            <span
              className={cn(
                "rounded-full border px-3 py-1 text-xs",
                loading
                  ? "border-slate-200 bg-slate-50 text-slate-500"
                  : runtimeReady
                    ? "border-emerald-100 bg-emerald-50 text-emerald-600"
                    : "border-amber-100 bg-amber-50 text-amber-600"
              )}
            >
              {loading ? "检测中" : runtimeReady ? "Runtime Ready" : "Runtime Missing"}
            </span>
          </DialogHeader>

          <div className="mt-10 flex items-center border-b border-slate-100 pb-6 text-sm">
            {["检测环境", "运行时决策", "准备 Runtime", "完成"].map((step, index) => {
              const isActive = currentStep === index + 1;
              const isDone = currentStep > index + 1;
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
                  {index < 3 ? <ArrowRight className="mx-4 h-4 w-4 text-slate-200" /> : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="min-h-[360px] overflow-hidden px-8 pt-2 pb-8">
          {error && !prototypeMode ? (
            <div className="mb-6 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-600">{error}</div>
          ) : null}
          {currentStep === 1 ? (
            <div className="grid grid-cols-12 gap-8">
              <div className="col-span-8 min-h-0 space-y-4">
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">检测环境</h3>
                  <p className="text-sm leading-relaxed text-slate-500">
                    先确认这台服务器是否具备运行条件，再决定是否继续走 Docker / Podman 容器模式，还是直接进入 Conda Runtime。
                  </p>
                </div>

                {prototypeMode ? (
                  <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-600">
                    <Info className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                    <div className="space-y-1">
                      <p className="font-medium text-slate-700">当前展示的是 UI 原型模式下的检测页。</p>
                      <p className="text-xs leading-relaxed text-slate-500">
                        后端检测/安装接口尚未接通时，页面先保持完整信息架构；等接口接上后，这里会自动替换为真实服务器返回结果。
                      </p>
                    </div>
                  </div>
                ) : null}

                <div className="grid gap-3 sm:grid-cols-3">
                  <Step1StatCard label="已就绪" value={checklistSummary.ready} tone="ready" />
                  <Step1StatCard label="需要确认" value={checklistSummary.warn + checklistSummary.blocked} tone="warn" />
                  <Step1StatCard label="缺失" value={checklistSummary.missing} tone="missing" />
                </div>

                <div className="max-h-[48vh] overflow-auto pr-2">
                  {checklistSections.map((section) => (
                    <section key={section.key} className="border-t border-slate-100 pt-4 first:pt-0">
                      <div className="mb-2 flex items-center justify-between gap-4">
                        <div className="space-y-0.5">
                          <h4 className="text-sm font-medium text-slate-900">{section.title}</h4>
                          <p className="text-xs leading-relaxed text-slate-500">{section.description}</p>
                        </div>
                        <span className="text-[11px] text-slate-400">{section.items.length} 项</span>
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

              <div className="col-span-4 pt-10">
                <div className="sticky top-0 space-y-4 rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                    <PackageSearch className="h-4 w-4 text-slate-400" /> 智能部署决策
                  </div>

                  <div className="space-y-3">
                    <div className="space-y-1">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">推荐 Profile</p>
                      <div className="flex items-center gap-2">
                        <span className="inline-flex rounded-md bg-slate-950 px-2.5 py-1 font-mono text-xs text-white">
                          {preflight?.recommended_profile || "personal_conda"}
                        </span>
                        <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                          当前推荐
                        </span>
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-100 bg-slate-50/70 px-4 py-3 text-sm leading-relaxed text-slate-600">
                      {recommendedExplanation}
                    </div>
                  </div>

                  <div className="space-y-2 border-t border-slate-100 pt-4 text-sm">
                    <div className="flex items-start gap-2 text-slate-600">
                      <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-500" />
                      <span>下一步会让你明确选择 Docker / Podman / Conda 路径。</span>
                    </div>
                    <div className="flex items-start gap-2 text-slate-600">
                      <Server className="mt-0.5 h-4 w-4 text-slate-400" />
                      <span>检测结果会直接决定后续是否需要引导用户自行安装 Docker。</span>
                    </div>
                  </div>

                  {preflight?.supported_profile_kinds?.length ? (
                    <div className="space-y-2 border-t border-slate-100 pt-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">可选运行方式</p>
                      <div className="flex flex-wrap gap-2">
                        {preflight.supported_profile_kinds.map((profile) => (
                          <span key={profile} className="rounded-full border border-slate-200 bg-white px-2.5 py-1 font-mono text-[11px] text-slate-500">
                            {profile}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {preflight?.warnings?.length ? (
                    <div className="rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-700">
                      {preflight.warnings[0]}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}

          {currentStep === 2 ? (
            <div className="space-y-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">选择运行方式</h3>
              {flowNotice ? (
                <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm text-blue-700">{flowNotice}</div>
              ) : null}
              {showDockerChoices ? (
                <div className="grid grid-cols-3 gap-4">
                  {[
                    {
                      key: "self_install_docker" as const,
                      title: "我会自己安装 Docker",
                      description: "推荐。适合你自己管理服务器或有管理员协助时使用。",
                      recommended: true,
                    },
                    {
                      key: "assistant_install_docker" as const,
                      title: "软件协助安装 Docker",
                      description: "实验性。需要 sudo，仅适用于部分 Linux 发行版。",
                      recommended: false,
                    },
                    {
                      key: "fallback_conda" as const,
                      title: "继续使用 Conda Runtime",
                      description: "无需 Docker。软件将准备 Micromamba 和 Nextflow。",
                      recommended: false,
                    },
                  ].map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setSelectedDecision(option.key)}
                      className={cn(
                        "rounded-xl border p-5 text-left transition",
                        selectedDecision === option.key
                          ? "border-slate-950 bg-slate-50"
                          : "border-slate-100 hover:border-slate-200"
                      )}
                    >
                      <div className="mb-3 flex items-center justify-between">
                        <h4 className="text-sm font-semibold text-slate-950">{option.title}</h4>
                        {option.recommended ? (
                          <span className="rounded-full bg-slate-950 px-2 py-0.5 text-[10px] text-white">推荐</span>
                        ) : null}
                      </div>
                      <p className="text-sm leading-relaxed text-slate-500">{option.description}</p>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-100 bg-white p-5 shadow-sm">
                  <p className="text-sm text-slate-700">
                    当前推荐继续使用 <strong>{preflight?.recommended_profile || "personal_conda"}</strong>。
                  </p>
                  <p className="mt-2 text-xs leading-relaxed text-slate-500">{recommendedExplanation}</p>
                </div>
              )}
            </div>
          ) : null}

          {currentStep === 3 ? (
            <div className="space-y-6">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">准备 Runtime</h3>
              {flowNotice ? (
                <div className="rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-sm text-blue-700">{flowNotice}</div>
              ) : null}
              {selectedDecision === "self_install_docker" ? (
                <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-5 text-sm text-slate-600">
                  未检测到 Docker。请先自行安装 Docker，然后点击“重新检查”继续。
                </div>
              ) : selectedDecision === "assistant_install_docker" ? (
                <>
                  <div className="rounded-xl border border-amber-100 bg-amber-50 p-5 text-sm text-amber-700">
                    软件协助安装 Docker 属于实验性能力。需要远端具备 root 或免密 sudo，并且仅支持部分 Linux 发行版。
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
                    <pre>{installSnapshot?.log_text || "等待开始协助安装 Docker..."}</pre>
                  </div>
                </>
              ) : (
                <>
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
                    <pre>{installSnapshot?.log_text || "等待开始准备 Runtime..."}</pre>
                  </div>
                </>
              )}
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
                  <RuntimePath label="Nextflow" value={runtimeSummary?.nextflowPath || "~/.h2ometa/runtime/bin/nextflow"} />
                  <RuntimePath label="Micromamba" value={runtimeSummary?.micromambaPath || "~/.h2ometa/runtime/bin/micromamba"} />
                  <RuntimePath label="Java" value={runtimeSummary?.javaPath || "使用系统 Java"} />
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
            {currentStep > 1 && currentStep < 4 ? (
              <Button
                variant="outline"
                className="rounded-lg border-slate-200 text-slate-700"
                onClick={() =>
                  setCurrentStep((step) => {
                    if (step === 4) return 3;
                    if (step === 3) return 2;
                    return 1;
                  })
                }
              >
                上一步
              </Button>
            ) : null}
            {currentStep === 1 ? (
              <Button variant="outline" className="rounded-lg border-slate-200 text-slate-700" onClick={() => void loadData()}>
                <RefreshCw className="mr-2 h-4 w-4" /> 重新检查
              </Button>
            ) : null}
            {currentStep === 1 ? (
              <Button className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800" onClick={() => setCurrentStep(2)}>
                下一步
              </Button>
            ) : null}
            {currentStep === 2 ? (
              <Button className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800" onClick={() => setCurrentStep(3)}>
                下一步
              </Button>
            ) : null}
            {currentStep === 3 ? (
              selectedDecision === "self_install_docker" ? (
                <Button className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800" onClick={() => void loadData()}>
                  我已安装，重新检查
                </Button>
              ) : selectedDecision === "assistant_install_docker" ? (
                <Button
                  className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800"
                  disabled={installRunning || !canRunBootstrap}
                  onClick={() => void beginBootstrap()}
                >
                  {prototypeMode ? "后端待接入" : installRunning ? "安装中..." : "开始协助安装 Docker"}
                </Button>
              ) : (
                <Button
                  className="rounded-lg bg-slate-950 px-8 text-white hover:bg-slate-800"
                  disabled={installRunning || !canRunBootstrap}
                  onClick={() => void beginBootstrap()}
                >
                  {prototypeMode ? "后端待接入" : installRunning ? "准备中..." : "开始准备 Runtime"}
                </Button>
              )
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


function Step1StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ready" | "warn" | "missing";
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        tone === "ready"
          ? "border-emerald-100 bg-emerald-50/70"
          : tone === "warn"
            ? "border-amber-100 bg-amber-50/70"
            : "border-red-100 bg-red-50/70"
      )}
    >
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</p>
      <div className="mt-2 flex items-end justify-between">
        <span className="text-2xl font-semibold text-slate-950">{value}</span>
        <span
          className={cn(
            "text-xs font-medium",
            tone === "ready"
              ? "text-emerald-700"
              : tone === "warn"
                ? "text-amber-700"
                : "text-red-700"
          )}
        >
          {tone === "ready" ? "可继续" : tone === "warn" ? "待确认" : "待处理"}
        </span>
      </div>
    </div>
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
