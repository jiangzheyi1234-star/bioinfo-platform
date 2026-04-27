"use client";

import { Database, Plus, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { WorkflowWorkspaceTabs } from "./workflow-workspace-tabs";

const databases = [
  {
    id: "kraken2-standard",
    name: "Kraken2 Standard",
    description: "物种分类标准数据库",
    version: "2026.04",
  },
  {
    id: "metaphlan",
    name: "MetaPhlAn marker database",
    description: "MetaPhlAn 标记基因数据库",
    version: "vOct22",
  },
  {
    id: "card",
    name: "CARD",
    description: "耐药基因注释数据库",
    version: "3.3.0",
  },
];

export function DatabasesPage() {
  return (
    <div className="relative h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <WorkflowWorkspaceTabs />
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex items-center justify-end">
          <Button variant="outline" className="h-9 bg-white px-3 text-slate-600">
            <Plus strokeWidth={1.5} className="mr-2 h-4 w-4" />
            添加数据库
          </Button>
        </div>

        <div className="text-center">
          <h1 className="text-2xl font-semibold">数据库</h1>
        </div>

        <div className="relative">
          <Search
            strokeWidth={1.5}
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500"
          />
          <Input
            type="text"
            placeholder="搜索数据库、版本或用途"
            className="h-10 w-full rounded-md border-slate-200 bg-white pl-9"
          />
        </div>

        <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
          {databases.map((item) => (
            <div
              key={item.id}
              className="flex items-center rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50"
            >
              <Database strokeWidth={1.5} className="mr-3 h-4 w-4 flex-shrink-0 text-zinc-500" />
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-sm font-medium text-slate-800">{item.name}</h3>
                <p className="mt-1 truncate text-xs text-slate-500">
                  {item.description} · {item.version}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
