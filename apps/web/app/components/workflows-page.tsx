"use client";

import {
  ArrowRight,
  FileText,
  Plus,
  Search,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

const workflowTemplates = [
  {
    id: "mq",
    title: "宏基因组标准质控 v1.0",
    description: "包含 fastp 与 bowtie2 的环境样本清理流程",
  },
  {
    id: "tp",
    title: "物种组成分析 v1.0",
    description: "使用 Kraken2 或 MetaPhlAn 进行物种注释",
  },
  {
    id: "aq",
    title: "组装与基因预测 v0.9",
    description: "使用 SPAdes 组装并进行基因预测与注释",
  },
  {
    id: "da",
    title: "差异丰度分析 v0.8",
    description: "基于物种/功能丰度进行差异分析与可视化",
  },
  {
    id: "rg",
    title: "报告生成模板 v1.0",
    description: "生成多模块汇总报告与可视化结果",
  },
  {
    id: "am",
    title: "耐药基因筛查 v0.7",
    description: "检测样本中的耐药基因及其丰度与来源",
  },
];

export function WorkflowsPage() {
  return (
    <div className="relative flex-1 w-full h-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header Options */}
        <div className="flex items-center justify-end gap-3">
          <Button variant="outline" className="h-9 bg-white px-3 text-slate-600">
            <FileText strokeWidth={1.5} className="w-4 h-4 mr-2" />
            我的草稿
          </Button>
          <Button variant="outline" className="h-9 bg-white px-3 text-slate-600">
            <Plus strokeWidth={1.5} className="w-4 h-4 mr-2" />
            新建空白流程
          </Button>
        </div>

        {/* Title */}
        <div className="text-center">
          <h1 className="text-2xl font-semibold">选择流程模板</h1>
        </div>

        {/* Toolbar */}
        <div className="grid grid-cols-1 gap-x-12 gap-y-3 md:grid-cols-2">
          <div className="relative">
            <Search
              strokeWidth={1.5}
              className="w-4 h-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-zinc-500"
            />
            <Input
              type="text"
              placeholder="搜索流程、模块或标签"
              className="h-10 w-full rounded-md border-slate-200 bg-white pl-9"
            />
          </div>
          <div className="flex items-center justify-end gap-4">
            <div className="flex h-10 cursor-pointer items-center rounded-md border border-slate-200 bg-white px-4 text-sm text-slate-600">
              来源: 官方
              <ChevronDown strokeWidth={1.5} className="w-4 h-4 ml-2 text-zinc-500" />
            </div>
            <div className="flex h-10 cursor-pointer items-center rounded-md border border-slate-200 bg-white px-4 text-sm text-slate-600">
              分类: 全部
              <ChevronDown strokeWidth={1.5} className="w-4 h-4 ml-2 text-zinc-500" />
            </div>
          </div>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
          {workflowTemplates.map((template) => (
            <div
              key={template.id}
              className={cn(
                "group flex items-center rounded-lg border border-transparent bg-white px-3 py-3",
                "transition-colors hover:border-slate-200 hover:bg-slate-50"
              )}
            >
              <div className="flex-1 min-w-0">
                <div className="flex justify-between items-start">
                  <h3 className="truncate text-sm font-medium text-slate-800">
                    {template.title}
                  </h3>
                </div>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {template.description}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="ml-3 h-8 w-8 flex-shrink-0 text-slate-400 hover:bg-white hover:text-slate-800"
                title="配置"
              >
                <ArrowRight strokeWidth={1.5} className="h-3.5 w-3.5" />
                <span className="sr-only">配置</span>
              </Button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
