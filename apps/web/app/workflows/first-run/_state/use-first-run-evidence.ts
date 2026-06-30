"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  downloadFirstRunHandoffManifest,
  downloadFirstRunValidationCard,
  downloadFirstRunValidationCardMarkdown,
  fetchFirstRunValidationCard,
  finalizeFirstRun,
} from "../_api/workflow-first-run-api";
import { firstRunResultPackageReady, mergePackageExport } from "../_domain/first-run-package";
import { workflowRevisionIdFor } from "../_domain/first-run-progress";
import type {
  FirstRunNextAction,
  FirstRunPilotHandoff,
  FirstRunStatus,
  FirstRunValidationCard,
} from "../_domain/first-run-types";
import {
  exportWorkflowResultPackage,
  fetchWorkflowResultPackageExports,
  fetchWorkflowScenarioPacks,
} from "@/app/components/workflows-page-api";
import {
  workflowErrorMessage,
  type WorkflowResultPackageExport,
  type WorkflowRun,
  type WorkflowRunDetail,
  type WorkflowScenarioPack,
} from "@/app/components/workflows-page-model";

export function useFirstRunEvidence({
  refreshRunDetail,
  resultId,
  run,
  runDetail,
  status,
  serverId,
}: {
  refreshRunDetail: () => Promise<WorkflowRunDetail | null>;
  resultId: string;
  run: WorkflowRun | null;
  runDetail: WorkflowRunDetail | null;
  status: FirstRunStatus | null;
  serverId?: string;
}) {
  const [packageExports, setPackageExports] = useState<WorkflowResultPackageExport[]>([]);
  const [packageLoading, setPackageLoading] = useState(false);
  const [packageError, setPackageError] = useState("");
  const [exportingPackage, setExportingPackage] = useState(false);
  const [finalizingFirstRun, setFinalizingFirstRun] = useState(false);
  const [finalizationAction, setFinalizationAction] = useState<FirstRunNextAction | null>(null);
  const [pilotHandoff, setPilotHandoff] = useState<FirstRunPilotHandoff | null>(null);
  const [validationCard, setValidationCard] = useState<FirstRunValidationCard | null>(null);
  const [validationCardFetchLoading, setValidationCardFetchLoading] = useState(false);
  const [validationCardFetchError, setValidationCardFetchError] = useState("");
  const [validationCardLoading, setValidationCardLoading] = useState(false);
  const [validationCardError, setValidationCardError] = useState("");
  const [nextScenarioPacks, setNextScenarioPacks] = useState<WorkflowScenarioPack[]>([]);
  const [nextScenarioPacksLoading, setNextScenarioPacksLoading] = useState(false);
  const [nextScenarioPacksError, setNextScenarioPacksError] = useState("");

  const statusRun = status?.evidence?.run || status?.latestEligibleRun || null;
  const statusPackageEvidence = status?.evidence?.resultPackage;
  const statusPackageExportId = statusPackageEvidence?.packageExportId || "";
  const readyPackage = useMemo(() => {
    if (statusPackageExportId) {
      return packageExports.find((item) => item.packageExportId === statusPackageExportId);
    }
    return packageExports.find(firstRunResultPackageReady);
  }, [packageExports, statusPackageExportId]);
  const statusPackageFallback = useMemo(() => {
    if (statusPackageEvidence?.ready !== true || !statusPackageExportId || !resultId) return undefined;
    return {
      artifactPayloadMode: statusPackageEvidence.artifactPayloadMode,
      download: {
        href: `/api/v1/results/${encodeURIComponent(resultId)}/exports/${encodeURIComponent(statusPackageExportId)}/download`,
      },
      includeArtifacts: statusPackageEvidence.includeArtifacts,
      lifecycleState: "active",
      manifestSha256: statusPackageEvidence.manifestSha256,
      packageBytesState: "available",
      packageExportId: statusPackageExportId,
      resultId,
      sha256: statusPackageEvidence.sha256,
    } satisfies WorkflowResultPackageExport;
  }, [resultId, statusPackageEvidence, statusPackageExportId]);
  const latestPackage = readyPackage || (status ? statusPackageFallback : packageExports[0]);
  const firstRunRunId = status ? statusRun?.runId || "" : run?.runId || "";
  const workflowRevisionId = status
    ? statusRun?.workflowRevisionId || ""
    : workflowRevisionIdFor(run, runDetail, latestPackage);
  const runStatus = status ? statusRun?.status || "" : run?.status || "";
  const runTerminal = runStatus === "completed" || runStatus === "failed" || runStatus === "error";
  const packageReady = status?.evidence?.resultPackage?.ready === true;
  const validationReady = status?.status === "ready" || status?.evidence?.validation?.ready === true;
  const validationEligible = validationReady;

  const loadPackageExports = useCallback(async () => {
    if (!resultId || !runTerminal) {
      setPackageExports([]);
      setPackageError("");
      return;
    }
    setPackageLoading(true);
    setPackageError("");
    try {
      setPackageExports(await fetchWorkflowResultPackageExports(resultId, { serverId }));
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "结果包记录加载失败"));
    } finally {
      setPackageLoading(false);
    }
  }, [resultId, runTerminal, serverId]);

  useEffect(() => {
    void loadPackageExports();
  }, [loadPackageExports]);

  const loadValidationCard = useCallback(async () => {
    if (!firstRunRunId || !validationEligible) {
      setValidationCard(null);
      setValidationCardFetchError("");
      return;
    }
    setValidationCardFetchLoading(true);
    setValidationCardFetchError("");
    try {
      setValidationCard(await fetchFirstRunValidationCard(firstRunRunId, { serverId }));
    } catch (err) {
      setValidationCard(null);
      setValidationCardFetchError(workflowErrorMessage(err, "验证卡加载失败"));
    } finally {
      setValidationCardFetchLoading(false);
    }
  }, [firstRunRunId, serverId, validationEligible]);

  useEffect(() => {
    void loadValidationCard();
  }, [loadValidationCard]);

  const loadNextScenarioPacks = useCallback(async () => {
    if (!validationReady) {
      setNextScenarioPacks([]);
      setNextScenarioPacksError("");
      return;
    }
    setNextScenarioPacksLoading(true);
    setNextScenarioPacksError("");
    try {
      const packs = await fetchWorkflowScenarioPacks();
      setNextScenarioPacks(packs.filter((pack) => pack.scenarioId !== "moving-pictures-16s"));
    } catch (err) {
      setNextScenarioPacks([]);
      setNextScenarioPacksError(workflowErrorMessage(err, "下一批试点场景读取失败"));
    } finally {
      setNextScenarioPacksLoading(false);
    }
  }, [validationReady]);

  useEffect(() => {
    void loadNextScenarioPacks();
  }, [loadNextScenarioPacks]);

  async function exportPackage() {
    if (!resultId || exportingPackage) return;
    setExportingPackage(true);
    setPackageError("");
    try {
      const exported = await exportWorkflowResultPackage(resultId, true, { serverId });
      setPackageExports((current) => mergePackageExport(exported, current));
      await refreshRunDetail();
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "结果包导出失败"));
    } finally {
      setExportingPackage(false);
    }
  }

  async function finalizeRun() {
    if (!firstRunRunId || finalizingFirstRun) return;
    setFinalizingFirstRun(true);
    setPackageError("");
    setValidationCardError("");
    setFinalizationAction(null);
    try {
      const finalized = await finalizeFirstRun(firstRunRunId, {
        actor: "first-run-ui",
        serverId,
      });
      if (finalized.status !== "ready" || !finalized.validationCard) {
        setFinalizationAction(finalized.nextAction || null);
        if (!finalized.nextAction) setPackageError("首跑完成被阻塞");
        return;
      }
      const packageExport = finalized.resultPackage;
      if (packageExport?.packageExportId) {
        setPackageExports((current) => mergePackageExport(packageExport, current));
      }
      setPilotHandoff(finalized.pilotHandoff || null);
      setValidationCard(finalized.validationCard);
      await refreshRunDetail();
    } catch (err) {
      setPackageError(workflowErrorMessage(err, "首跑完成失败"));
    } finally {
      setFinalizingFirstRun(false);
    }
  }

  async function downloadValidationCard() {
    if (!firstRunRunId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunValidationCard({
        card: validationCard,
        resultId,
        runId: firstRunRunId,
        serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "验证卡生成失败"));
    } finally {
      setValidationCardLoading(false);
    }
  }

  async function downloadValidationCardMarkdown() {
    if (!firstRunRunId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunValidationCardMarkdown({
        card: validationCard,
        resultId,
        runId: firstRunRunId,
        serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "验证卡 Markdown 生成失败"));
    } finally {
      setValidationCardLoading(false);
    }
  }

  async function downloadHandoffManifest() {
    if (!firstRunRunId || validationCardLoading) return;
    setValidationCardLoading(true);
    setValidationCardError("");
    try {
      await downloadFirstRunHandoffManifest({
        card: validationCard,
        resultId,
        runId: firstRunRunId,
        serverId,
      });
    } catch (err) {
      setValidationCardError(workflowErrorMessage(err, "交接清单生成失败"));
    } finally {
      setValidationCardLoading(false);
    }
  }

  return {
    downloadHandoffManifest,
    downloadValidationCard,
    downloadValidationCardMarkdown,
    exportPackage,
    exportingPackage,
    finalizationAction,
    finalizingFirstRun,
    finalizeRun,
    latestPackage,
    loadPackageExports,
    nextScenarioPacks,
    nextScenarioPacksError,
    nextScenarioPacksLoading,
    packageError,
    packageLoading,
    packageReady,
    pilotHandoff,
    validationCard,
    validationCardError,
    validationCardFetchError,
    validationCardFetchLoading,
    validationCardLoading,
    validationEligible,
    validationReady,
    workflowRevisionId,
  };
}
