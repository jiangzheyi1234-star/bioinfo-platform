"use client";

import {
  Clipboard,
  Database,
  Eye,
  MoreHorizontal,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { databaseStatusMessage, statusText, type DatabaseItem } from "./database-page-model";

type DatabaseItemListProps = {
  items: DatabaseItem[];
  checkingId: string;
  getDatabaseToolPath: (item: DatabaseItem) => string;
  templateText: (item: DatabaseItem) => string;
  openEditDatabase: (item: DatabaseItem) => void;
  copyDatabasePath: (path: string) => Promise<void>;
  setDetailsItem: (item: DatabaseItem | null) => void;
  onCheck: (id: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
};

export function DatabaseItemList({
  items,
  checkingId,
  getDatabaseToolPath,
  templateText,
  openEditDatabase,
  copyDatabasePath,
  setDetailsItem,
  onCheck,
  onRemove,
}: DatabaseItemListProps) {
  return (
    <div className="grid grid-cols-1 gap-x-12 gap-y-2 md:grid-cols-2">
      {items.map((item) => {
        const toolPath = getDatabaseToolPath(item);
        const statusTextValue = statusText(item);
        const statusMessage = databaseStatusMessage(item);
        const templateTextValue = templateText(item);

        return (
          <div
            key={item.id}
            className="group flex items-center rounded-lg border border-transparent bg-white px-3 py-3 transition-colors hover:border-slate-200 hover:bg-slate-50 focus-within:border-slate-200 focus-within:bg-slate-50"
          >
            <Database strokeWidth={1.5} className="mr-3 h-4 w-4 flex-shrink-0 text-zinc-500" />
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-sm font-medium text-slate-800">{item.name}</h3>
              <p className="mt-1 truncate text-xs text-slate-500">
                {templateTextValue} {item.version ? `· ${item.version}` : ""} · {statusTextValue}
              </p>
              {statusMessage ? <p className="mt-1 truncate text-xs text-slate-400">{statusMessage}</p> : null}
              {toolPath && toolPath !== item.path ? (
                <p className="mt-1 truncate font-mono text-[11px] text-slate-400" title={`实际工具路径：${toolPath}`}>
                  实际工具路径：{toolPath}
                </p>
              ) : null}
            </div>
            <div className="ml-3 flex items-center gap-1">
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-slate-400 opacity-0 transition-opacity hover:text-slate-700 group-hover:opacity-100 group-focus-within:opacity-100 data-[state=open]:opacity-100"
                    aria-label={`${item.name} 操作`}
                  >
                    <MoreHorizontal strokeWidth={1.5} className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onSelect={() => openEditDatabase(item)}>
                    <Pencil strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    重命名
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => copyDatabasePath(toolPath || item.path)}>
                    <Clipboard strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    复制实际工具路径
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => setDetailsItem(item)}>
                    <Eye strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    查看校验详情
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onCheck(item.id)}>
                    <RefreshCw strokeWidth={1.5} className={cn("mr-2 h-4 w-4", checkingId === item.id && "animate-spin")} />
                    重新校验
                  </DropdownMenuItem>
                  <DropdownMenuItem destructive onSelect={() => onRemove(item.id)}>
                    <Trash2 strokeWidth={1.5} className="mr-2 h-4 w-4" />
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        );
      })}
    </div>
  );
}
