"use client";

import type { ReactNode } from "react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type DatabaseValidationDetailsItem = {
  name: string;
  path: string;
  status: string;
  message: string;
  updatedAt: string;
  lastCheckedAt: string | null;
  metadata?: {
    availableReadLengths?: number[];
    resolvedPath?: {
      kind?: string;
      path?: string;
      prefix?: string;
      firstMatch?: string;
      firstIndexPrefix?: string;
    };
    validation?: {
      toolProbe?: {
        ok?: boolean;
        command?: string;
        returncode?: number;
        stdout?: string;
        stderr?: string;
      };
    };
  };
};

type ToolProbe = NonNullable<NonNullable<DatabaseValidationDetailsItem["metadata"]>["validation"]>["toolProbe"];

type DatabaseValidationDetailsDialogProps = {
  open: boolean;
  item: DatabaseValidationDetailsItem | null;
  toolPath: string;
  onOpenChange: (open: boolean) => void;
};

function DetailRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={mono ? "break-all rounded-md bg-slate-50 px-2 py-1.5 font-mono text-xs text-slate-700" : "text-sm text-slate-800"}>
        {value || "无"}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      {children}
    </section>
  );
}

function TerminalBlock({ label, value, emptyText }: { label: string; value?: string; emptyText: string }) {
  const content = value && value.length > 0 ? value : emptyText;

  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs leading-5 text-slate-100">
        {content}
      </pre>
    </div>
  );
}

function databaseStatusText(status: string) {
  if (status === "available") return "可用";
  if (status === "missing") return "缺失";
  if (status === "failed") return "验证失败";
  if (status === "declared") return "未校验";
  return status || "未校验";
}

function toolProbeStatusText(probe?: ToolProbe) {
  if (!probe) return "未配置";
  return probe.ok ? "通过" : "失败";
}

function pathResolutionExplanation(kind?: string) {
  if (kind === "prefix") {
    return "选择路径可以是索引目录或某个索引文件；保存后会解析为去掉索引后缀的 prefix，并把这个 prefix 传给工具。";
  }
  if (kind === "primary_with_sidecars") {
    return "选择路径应是 FASTA 主文件；保存后工具继续使用该 FASTA 文件，并验证同名前缀的 BWA 索引文件是否存在。";
  }
  if (kind === "composite") {
    return "复合数据库由多个目录或文件组成；保存时会按模板字段解析并校验每个输入路径。";
  }
  if (kind === "file") {
    return "选择路径是数据库文件；如果选择的是只有一个候选文件的目录，后端会解析到实际文件后传给工具。";
  }
  return "选择路径是数据库目录；工具直接使用该目录并按模板规则验证。";
}

export function DatabaseValidationDetailsDialog({ open, item, toolPath, onOpenChange }: DatabaseValidationDetailsDialogProps) {
  const probe = item?.metadata?.validation?.toolProbe;
  const resolved = item?.metadata?.resolvedPath;
  const readLengths = item?.metadata?.availableReadLengths || [];
  const commandEmptyText = probe ? "工具探测已执行，但未记录实际执行命令。" : "该模板未配置工具探测，暂无实际执行命令。";
  const stdoutEmptyText = probe ? "未捕获 stdout；许多成功探测会把 stdout 重定向到 /dev/null。" : "该模板未配置工具探测，暂无 stdout。";
  const stderrEmptyText = probe ? "未捕获 stderr。" : "该模板未配置工具探测，暂无 stderr。";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>校验详情</DialogTitle>
          <DialogDescription>查看该数据库最近一次路径解析和工具探测的真实执行结果。</DialogDescription>
        </DialogHeader>
        {item ? (
          <div className="mt-5 flex max-h-[65vh] flex-col gap-4 overflow-y-auto pr-1">
            <Section title="数据库路径">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <DetailRow label="数据库" value={item.name} />
                <DetailRow label="选择路径" value={item.path} mono />
                <DetailRow label="实际工具路径" value={toolPath || item.path} mono />
                <DetailRow label="解析类型" value={resolved?.kind || ""} />
              </div>
              <DetailRow label="路径如何传给工具" value={pathResolutionExplanation(resolved?.kind)} />
            </Section>

            <Section title="校验结果">
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <DetailRow label="状态" value={databaseStatusText(item.status)} />
                <DetailRow label="工具探测：" value={toolProbeStatusText(probe)} />
                <DetailRow label="最后校验时间" value={item.lastCheckedAt || item.updatedAt || ""} />
                <DetailRow label="返回码" value={probe?.returncode === undefined ? (probe ? "未记录" : "未配置") : String(probe.returncode)} />
              </div>
              {readLengths.length > 0 ? <DetailRow label="可用 read lengths" value={readLengths.join(", ")} /> : null}
              {item.message ? <DetailRow label="状态信息" value={item.message} /> : null}
            </Section>

            <Section title="工具探测输出">
              <TerminalBlock label="实际执行命令" value={probe?.command} emptyText={commandEmptyText} />
              <TerminalBlock label="stdout" value={probe?.stdout} emptyText={stdoutEmptyText} />
              <TerminalBlock label="stderr" value={probe?.stderr} emptyText={stderrEmptyText} />
            </Section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
