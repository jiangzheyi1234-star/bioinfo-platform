"use client";

import { apiBase } from "@/app/lib/local-api-client";

import type { FirstRunEvidenceBundle, FirstRunEvidenceBundleFile } from "./first-run-types";

export const FIRST_RUN_EVIDENCE_BUNDLE_DOWNLOAD_ROLES = [
  "result-package",
  "validation-card-markdown",
  "pilot-handoff",
  "validation-card-json",
] as const;

export type FirstRunEvidenceBundleDownloadRole = (typeof FIRST_RUN_EVIDENCE_BUNDLE_DOWNLOAD_ROLES)[number];

export function firstRunEvidenceBundleFiles(
  bundle: FirstRunEvidenceBundle | null | undefined
): FirstRunEvidenceBundleFile[] {
  return FIRST_RUN_EVIDENCE_BUNDLE_DOWNLOAD_ROLES.map((role) => firstRunEvidenceBundleFileByRole(bundle, role)).filter(
    (file): file is FirstRunEvidenceBundleFile => Boolean(file && firstRunEvidenceBundleFileDownloadHref(file))
  );
}

export function firstRunEvidenceBundleFileByRole(
  bundle: FirstRunEvidenceBundle | null | undefined,
  role: FirstRunEvidenceBundleDownloadRole
): FirstRunEvidenceBundleFile | undefined {
  return (bundle?.requiredFiles || []).find((item) => item.role === role);
}

export function firstRunEvidenceBundleDownloadHref(bundle: FirstRunEvidenceBundle | null | undefined): string {
  return firstRunEvidenceBundleFileDownloadHref(bundle?.download);
}

export function firstRunEvidenceBundleFileDownloadHref(file: FirstRunEvidenceBundleFile | null | undefined): string {
  const href = String(file?.href || "").trim();
  if (!href.startsWith("/api/v1/") || href.includes("://") || href.startsWith("//")) return "";
  return `${apiBase()}${href}`;
}
