import { ExternalLink, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import type { ToolSearchItem } from "./tools-page-model";

export function ToolWrapperSelector({
  onOpenSourceUrl,
  onWrapperChange,
  selected,
  selectedWrapperPath,
}: {
  onOpenSourceUrl: (url: string) => void;
  onWrapperChange: (wrapperPath: string) => void;
  selected: ToolSearchItem;
  selectedWrapperPath: string;
}) {
  const wrappers = selected.snakemakeWrappers || [];
  const selectedWrapper = wrappers.find((wrapper) => wrapper.wrapperPath === selectedWrapperPath) || wrappers[0];
  if (wrappers.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="text-[11px] uppercase text-slate-400">Snakemake wrapper</div>
        <div className="mt-1 text-xs leading-5 text-slate-500">未命中同名官方 wrapper；需要补全 RuleSpec 后才能加入流程。</div>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50 p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="inline-flex items-center text-[11px] uppercase text-violet-600">
          <Workflow strokeWidth={1.5} className="mr-1 h-3 w-3" />
          Snakemake wrapper
        </div>
        <span className="text-[11px] text-violet-600">{wrappers.length} 个命中</span>
      </div>
      <Select value={selectedWrapper?.wrapperPath || ""} onValueChange={onWrapperChange}>
        <SelectTrigger className="h-9 bg-white text-xs">
          <SelectValue placeholder="选择 wrapper" />
        </SelectTrigger>
        <SelectContent>
          {wrappers.map((wrapper) => (
            <SelectItem key={wrapper.wrapperPath} value={wrapper.wrapperPath}>
              {wrapper.wrapperPath}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="mt-2 flex min-w-0 items-center justify-between gap-2">
        <div className="min-w-0 text-[11px] leading-4 text-violet-700">
          推荐 wrapper ref: <span className="font-mono">{selectedWrapper?.wrapperRef || "未声明"}</span>
        </div>
        {selectedWrapper?.wrapperUrl ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0 text-violet-700 hover:bg-white"
            onClick={() => onOpenSourceUrl(selectedWrapper.wrapperUrl)}
            title="查看 wrapper"
          >
            <ExternalLink strokeWidth={1.5} className="h-3.5 w-3.5" />
            <span className="sr-only">查看 wrapper</span>
          </Button>
        ) : null}
      </div>
    </div>
  );
}
