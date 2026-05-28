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
    <div className="relative flex min-h-14 flex-col items-stretch justify-center gap-3 pt-9 sm:h-14 sm:flex-row sm:items-center sm:pt-0">
      {leading ? (
        <div className="flex items-center gap-2 sm:absolute sm:left-0 sm:top-1/2 sm:-translate-y-1/2">{leading}</div>
      ) : null}
      <h1 className="text-left text-xl font-semibold tracking-normal text-slate-950 sm:text-center sm:text-2xl">{title}</h1>
      {actions ? (
        <div className="flex items-center gap-2 sm:absolute sm:right-0 sm:top-1/2 sm:-translate-y-1/2">{actions}</div>
      ) : null}
    </div>
  );
}
