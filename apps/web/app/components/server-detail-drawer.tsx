"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type ServerDetailDrawerProps = {
  serverId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ServerDetailDrawer({ serverId, open, onOpenChange }: ServerDetailDrawerProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>服务器详情</DialogTitle>
          <DialogDescription>查看当前远程连接和 runner 准备状态。</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Server</div>
            <div className="mt-1 break-all font-mono text-sm text-slate-900">{serverId || "未连接"}</div>
          </div>
          <p className="text-sm leading-6 text-slate-600">
            如果 runner 仍在准备中，连接状态会在后台刷新；准备完成后即可运行远程 workflow。
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
