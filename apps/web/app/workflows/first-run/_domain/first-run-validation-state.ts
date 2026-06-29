import type { FirstRunValidationCard } from "./first-run-types";

export function firstRunValidationCardPassed(card: FirstRunValidationCard | null) {
  const checks = card?.checks || [];
  const requiredBundleRoles = ["result-package", "validation-card-json", "validation-card-markdown", "pilot-handoff"];
  const bundleFiles = card?.pilotHandoff?.evidenceBundle?.requiredFiles || [];
  const bundleReady =
    card?.pilotHandoff?.evidenceBundle?.status === "ready" &&
    requiredBundleRoles.every((role) => bundleFiles.some((item) => item.role === role && item.filename));
  return (
    Boolean(card) &&
    checks.length > 0 &&
    checks.every((item) => item.status === "passed") &&
    card?.reportInterpretation?.status === "ready" &&
    card?.sampleData?.status === "verified" &&
    card?.softwareEnvironment?.status === "verified" &&
    Boolean(card?.pilotHandoff?.backupRestore) &&
    bundleReady &&
    Boolean(card?.resultPackage?.sha256) &&
    Boolean(card?.resultPackage?.manifestSha256)
  );
}
