"use client";

import { useEffect } from "react";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";

import { NAV_ITEMS } from "./detection_workspace_shell";

export function useDetectionWorkspaceHotkeys(router: AppRouterInstance) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTypingTarget =
        !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
      if (isTypingTarget || !event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
        return;
      }

      const index = Number(event.key) - 1;
      const targetItem = index >= 0 && index < NAV_ITEMS.length ? NAV_ITEMS[index] : null;
      if (!targetItem) {
        return;
      }
      event.preventDefault();
      router.push(targetItem.href);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [router]);
}
