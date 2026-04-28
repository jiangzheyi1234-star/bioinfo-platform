"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const tabs = [
  { href: "/workflows", label: "流程" },
  { href: "/workflows/databases", label: "数据库" },
  { href: "/workflows/tools", label: "工具" },
];

export function WorkflowWorkspaceTabs() {
  const pathname = usePathname();

  return (
    <div className="absolute left-3 top-2 z-20 flex h-8 items-center gap-3">
      {tabs.map((tab) => {
        const active =
          tab.href === "/workflows"
            ? pathname === tab.href
            : pathname === tab.href || pathname.startsWith(`${tab.href}/`);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex h-8 items-center px-1 text-xs transition",
              active
                ? "text-slate-900 after:absolute after:inset-x-1 after:bottom-0 after:h-0.5 after:bg-blue-500"
                : "text-slate-500 hover:text-slate-800"
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
