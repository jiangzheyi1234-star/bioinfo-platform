"use client";

import type { ReactNode } from "react";

export function WorkflowPageHeader({
  title,
  leading,
  actions,
}: {
  title: string;
  leading?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="relative flex h-14 items-center justify-center">
      {leading ? <div className="absolute left-0 top-1/2 flex -translate-y-1/2 items-center gap-2">{leading}</div> : null}
      <h1 className="text-2xl font-semibold tracking-normal text-slate-950">{title}</h1>
      {actions ? <div className="absolute right-0 top-1/2 flex -translate-y-1/2 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
