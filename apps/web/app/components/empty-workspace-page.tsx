"use client";

export function EmptyWorkspacePage() {
  return (
    <div className="flex h-full min-h-0 items-center justify-center bg-white text-slate-500">
      <div className="text-center">
        <p className="text-sm">未打开页面</p>
        <p className="mt-1 text-xs text-slate-400">从左侧导航选择一个工作区。</p>
      </div>
    </div>
  );
}
