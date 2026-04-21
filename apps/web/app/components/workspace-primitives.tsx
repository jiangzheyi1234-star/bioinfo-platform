import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowUpRight, ChevronRight, Copy, FileWarning, TerminalSquare } from "lucide-react";

import { cn } from "@/lib/utils";

import type { RunStatus } from "./workspace-mocks";

export function WorkspaceEyebrow({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{children}</p>;
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="flex flex-wrap items-center gap-1 text-[12px] text-slate-500">
      {items.map((item, index) => {
        const content = item.href ? (
          <Link href={item.href} className="transition hover:text-slate-700">
            {item.label}
          </Link>
        ) : (
          <span className="text-slate-600">{item.label}</span>
        );

        return (
          <span key={`${item.label}-${index}`} className="inline-flex items-center gap-1.5">
            {index > 0 ? <ChevronRight className="h-3 w-3 text-slate-300" /> : null}
            {content}
          </span>
        );
      })}
    </nav>
  );
}

export function WorkspacePageHeader({
  eyebrow = "Workspace",
  breadcrumbs,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  breadcrumbs?: { label: string; href?: string }[];
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <WorkspaceEyebrow>{eyebrow}</WorkspaceEyebrow>
        {breadcrumbs?.length ? <div className="mt-3"><Breadcrumbs items={breadcrumbs} /></div> : null}
        <h1 className="mt-2 text-[24px] font-semibold tracking-[-0.02em] text-slate-900">{title}</h1>
        {description ? <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-600">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function WorkspaceActionButton({
  children,
  href,
  variant = "ghost",
  leadingIcon,
  onClick,
  disabled = false,
}: {
  children: ReactNode;
  href?: string;
  variant?: "ghost" | "primary";
  leadingIcon?: "copy" | "terminal";
  onClick?: () => void;
  disabled?: boolean;
}) {
  const classes = cn(
    "inline-flex h-9 items-center justify-center gap-2 rounded-lg px-3 text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50",
    variant === "ghost"
      ? "border border-transparent bg-transparent text-slate-700 hover:bg-slate-100 hover:text-slate-900"
      : "bg-slate-900 text-white hover:bg-slate-800"
  );
  const icon =
    leadingIcon === "copy" ? <Copy className="h-4 w-4" /> : leadingIcon === "terminal" ? <TerminalSquare className="h-4 w-4" /> : null;

  if (href) {
    return (
      <Link href={href} className={classes}>
        {icon}
        {children}
      </Link>
    );
  }

  return (
    <button type="button" className={classes} onClick={onClick} disabled={disabled}>
      {icon}
      {children}
    </button>
  );
}

export function SummaryStrip({ items }: { items: { label: string; value: ReactNode; hint?: ReactNode }[] }) {
  return (
    <section className="grid gap-3 rounded-2xl bg-slate-50/90 p-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="rounded-xl bg-white/60 px-3 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{item.label}</p>
          <div className="mt-2 text-[13px] font-medium text-slate-900">{item.value}</div>
          {item.hint ? <div className="mt-1 text-[12px] text-slate-500">{item.hint}</div> : null}
        </div>
      ))}
    </section>
  );
}

export function WorkspaceSection({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-200/80 bg-white/95 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">{title}</h2>
          {description ? <p className="mt-1 text-[13px] leading-6 text-slate-500">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

const STATUS_STYLES: Record<RunStatus, { dot: string; text: string; bg: string }> = {
  queued: { dot: "bg-slate-400", text: "text-slate-600", bg: "bg-slate-100" },
  running: { dot: "bg-sky-500", text: "text-sky-700", bg: "bg-sky-50" },
  completed: { dot: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50" },
  failed: { dot: "bg-rose-500", text: "text-rose-700", bg: "bg-rose-50" },
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const style = STATUS_STYLES[status];
  return (
    <span className={cn("inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-[12px] font-medium", style.bg, style.text)}>
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} />
      {status}
    </span>
  );
}

export function FilterPill({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-9 items-center justify-between rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 transition hover:border-slate-300 hover:bg-slate-50",
        wide ? "min-w-[240px]" : "min-w-[120px]"
      )}
    >
      <span>{children}</span>
      <ChevronRight className="h-4 w-4 rotate-90 text-slate-400" />
    </button>
  );
}

export function SearchField({ placeholder }: { placeholder: string }) {
  return (
    <div className="flex h-9 min-w-[280px] items-center rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-500">
      <span>{placeholder}</span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-12 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-slate-200 bg-white text-slate-300">
        <FileWarning className="h-8 w-8" />
      </div>
      <h3 className="mt-4 text-[15px] font-medium text-slate-900">{title}</h3>
      <p className="mt-2 max-w-md text-sm leading-6 text-slate-500">{description}</p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function DataRow({
  href,
  children,
}: {
  href?: string;
  children: ReactNode;
}) {
  const content = (
    <div className="group grid min-h-14 items-center gap-3 rounded-xl px-3 py-2 transition hover:bg-slate-50">{children}</div>
  );

  if (!href) {
    return content;
  }

  return (
    <Link href={href} className="block">
      {content}
    </Link>
  );
}

export function ExternalAffordance() {
  return <ArrowUpRight className="h-4 w-4 text-slate-300 transition group-hover:text-slate-500" />;
}
