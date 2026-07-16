"use client";

import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { AlertCircle, FileText, Loader2, ShieldCheck, Sparkles } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { DEFAULT_AGENT_BUDGET, type AgentBudget } from "./agent-workbench-model";

const MAX_FASTQ_BYTES = 32 * 1024 * 1024;

const BUDGET_FIELDS: Array<{
  key: keyof AgentBudget;
  label: string;
  description: string;
  min: number;
  max: number;
}> = [
  {
    key: "maxModelTurns",
    label: "模型轮次",
    description: "确定性首版固定为 1；后续 provider 仍受此上限约束。",
    min: 1,
    max: 1_000,
  },
  {
    key: "maxToolCalls",
    label: "工具调用",
    description: "FastQC 与 MultiQC 的规划调用上限。",
    min: 0,
    max: 10_000,
  },
  {
    key: "maxReplans",
    label: "重规划",
    description: "当前 FASTQ adapter 没有 typed adjustment，建议保持 0。",
    min: 0,
    max: 100,
  },
  {
    key: "maxRetries",
    label: "规划重试",
    description: "只约束规划，不授权 workflow run 重试。",
    min: 0,
    max: 100,
  },
  {
    key: "maxWallClockSeconds",
    label: "最长秒数",
    description: "会话规划阶段的 wall-clock ceiling。",
    min: 1,
    max: 604_800,
  },
];

export type AgentGoalComposerSubmission = {
  projectId: string;
  summary: string;
  successCriterion: string;
  file: File;
  budget: AgentBudget;
};

export type AgentGoalComposerProps = {
  busy?: boolean;
  disabled?: boolean;
  error?: string;
  initialBudget?: AgentBudget;
  initialProjectId?: string;
  initialSuccessCriterion?: string;
  initialSummary?: string;
  onSubmit: (submission: AgentGoalComposerSubmission) => void | Promise<void>;
};

export function AgentGoalComposer({
  busy = false,
  disabled = false,
  error = "",
  initialBudget = DEFAULT_AGENT_BUDGET,
  initialProjectId = "project-fastq-qc",
  initialSuccessCriterion = "生成可审查的 FastQC 证据和 MultiQC HTML 报告。",
  initialSummary = "检查这个 FASTQ 的测序质量并生成汇总报告。",
  onSubmit,
}: AgentGoalComposerProps) {
  const [projectId, setProjectId] = useState(initialProjectId);
  const [summary, setSummary] = useState(initialSummary);
  const [successCriterion, setSuccessCriterion] = useState(initialSuccessCriterion);
  const [file, setFile] = useState<File | null>(null);
  const [budget, setBudget] = useState<AgentBudget>({ ...initialBudget });
  const [validationError, setValidationError] = useState("");
  const fileSummary = useMemo(() => fastqFileSummary(file), [file]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = validateSubmission({ budget, file, projectId, successCriterion, summary });
    if (problem) {
      setValidationError(problem);
      return;
    }
    setValidationError("");
    void onSubmit({
      projectId: projectId.trim(),
      summary: summary.trim(),
      successCriterion: successCriterion.trim(),
      file: file as File,
      budget: { ...budget },
    });
  }

  function updateBudget(key: keyof AgentBudget, raw: string) {
    const parsed = Number(raw);
    setBudget((current) => ({
      ...current,
      [key]: Number.isFinite(parsed) ? Math.trunc(parsed) : 0,
    }));
  }

  return (
    <section
      className="rounded-xl border border-slate-200 bg-white"
      aria-labelledby="agent-goal-composer-title"
      data-testid="agent-goal-composer"
    >
      <div className="border-b border-slate-100 px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-50 text-blue-700">
            <Sparkles strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 id="agent-goal-composer-title" className="text-sm font-semibold text-slate-950">
              描述研究目标
            </h2>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              从目标和输入开始。H2OMeta 会生成可验证方案，不要求先拖拽 DAG。
            </p>
          </div>
        </div>
      </div>

      <form className="space-y-5 px-5 py-5" onSubmit={submit} noValidate>
        {(validationError || error) ? (
          <Alert variant="destructive" data-testid="agent-goal-error">
            <AlertCircle strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
            <AlertTitle>暂时无法创建会话</AlertTitle>
            <AlertDescription>{validationError || error}</AlertDescription>
          </Alert>
        ) : null}

        <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
          <Field label="项目 ID" htmlFor="agent-project-id" description="用于隔离 draft 与 revision lineage。">
            <Input
              id="agent-project-id"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              disabled={disabled || busy}
              autoComplete="off"
              className="font-mono text-xs"
              data-testid="agent-project-id"
            />
          </Field>
          <Field label="科学目标" htmlFor="agent-goal-summary" description="描述希望得到的科学结果，而不是实现步骤。">
            <Input
              id="agent-goal-summary"
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              disabled={disabled || busy}
              autoComplete="off"
              data-testid="agent-goal-summary"
            />
          </Field>
        </div>

        <Field
          label="成功标准"
          htmlFor="agent-success-criterion"
          description="审批时会与输入、工具修订和预期产物一起显示。"
        >
          <Input
            id="agent-success-criterion"
            value={successCriterion}
            onChange={(event) => setSuccessCriterion(event.target.value)}
            disabled={disabled || busy}
            autoComplete="off"
            data-testid="agent-success-criterion"
          />
        </Field>

        <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex items-start gap-3">
            <FileText strokeWidth={1.5} className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <Label htmlFor="agent-fastq-file">单个 FASTQ 输入</Label>
              <p id="agent-fastq-file-help" className="mt-1 text-xs leading-5 text-slate-500">
                只接受一个非压缩的 .fastq 或 .fq 文件，不能为空且最大 32 MiB。
              </p>
              <Input
                id="agent-fastq-file"
                type="file"
                accept=".fastq,.fq,text/plain"
                aria-describedby="agent-fastq-file-help"
                disabled={disabled || busy}
                className="mt-3 cursor-pointer bg-white text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-700"
                data-testid="agent-fastq-file"
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  setFile(files.length === 1 ? files[0] : null);
                  setValidationError(files.length > 1 ? "一次只能提交一个 FASTQ 文件。" : "");
                }}
              />
              {fileSummary ? (
                <div className="mt-2 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800" data-testid="agent-fastq-file-summary">
                  {fileSummary}
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold text-slate-900">规划预算上限</legend>
          <p className="text-xs leading-5 text-slate-500">
            这些是硬上限，Agent 不能自行提高；它们不构成 workflow run 授权。
          </p>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {BUDGET_FIELDS.map((field) => (
              <div key={field.key} className="rounded-lg border border-slate-200 bg-white p-3">
                <Label htmlFor={`agent-budget-${field.key}`} className="text-xs">
                  {field.label}
                </Label>
                <Input
                  id={`agent-budget-${field.key}`}
                  type="number"
                  min={field.min}
                  max={field.max}
                  step={1}
                  value={budget[field.key]}
                  disabled={disabled || busy}
                  className="mt-2 h-8 font-mono text-xs"
                  data-testid={`agent-budget-${field.key}`}
                  onChange={(event) => updateBudget(field.key, event.target.value)}
                />
                <p className="mt-2 text-[11px] leading-4 text-slate-500">{field.description}</p>
              </div>
            ))}
          </div>
        </fieldset>

        <div className="rounded-lg border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs text-blue-900">
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />
            固定安全边界
          </div>
          <p className="mt-1 leading-5 text-blue-800">
            确定性 FastQC 0.12.1 → MultiQC 1.34；只选择已验证 capability bundle，禁止任意 shell 和未声明网络访问。审批只编译不可变 WorkflowRevision，不提交 Run。
          </p>
        </div>

        <div className="flex justify-end">
          <Button
            type="submit"
            disabled={disabled || busy}
            aria-busy={busy}
            data-testid="agent-create-and-plan"
          >
            {busy ? <Loader2 strokeWidth={1.5} className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Sparkles strokeWidth={1.5} className="h-4 w-4" aria-hidden="true" />}
            {busy ? "正在创建并规划" : "创建并生成方案"}
          </Button>
        </div>
      </form>
    </section>
  );
}

function Field({
  children,
  description,
  htmlFor,
  label,
}: {
  children: ReactNode;
  description: string;
  htmlFor: string;
  label: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      <p className="text-[11px] leading-4 text-slate-500">{description}</p>
    </div>
  );
}

function validateSubmission({
  budget,
  file,
  projectId,
  successCriterion,
  summary,
}: {
  budget: AgentBudget;
  file: File | null;
  projectId: string;
  successCriterion: string;
  summary: string;
}) {
  if (!projectId.trim()) return "项目 ID 不能为空。";
  if (!summary.trim()) return "科学目标不能为空。";
  if (!successCriterion.trim()) return "成功标准不能为空。";
  if (!file) return "请选择一个 FASTQ 文件。";
  const lowerName = file.name.trim().toLowerCase();
  if (lowerName.endsWith(".gz") || lowerName.endsWith(".gzip")) {
    return "当前 FASTQ adapter 不支持 gzip；请提供未压缩的 .fastq 或 .fq 文件。";
  }
  if (!lowerName.endsWith(".fastq") && !lowerName.endsWith(".fq")) {
    return "输入必须是 .fastq 或 .fq 文件。";
  }
  if (file.size < 1) return "FASTQ 文件不能为空。";
  if (file.size > MAX_FASTQ_BYTES) return "FASTQ 文件不能超过 32 MiB。";
  for (const field of BUDGET_FIELDS) {
    const value = budget[field.key];
    if (!Number.isInteger(value) || value < field.min || value > field.max) {
      return `${field.label}必须是 ${field.min} 到 ${field.max} 之间的整数。`;
    }
  }
  return "";
}

function fastqFileSummary(file: File | null) {
  if (!file) return "";
  const size = file.size < 1024
    ? `${file.size} B`
    : file.size < 1024 * 1024
      ? `${(file.size / 1024).toFixed(1)} KiB`
      : `${(file.size / (1024 * 1024)).toFixed(1)} MiB`;
  return `${file.name} · ${size} · 上传时固定校验为 text/plain`;
}
