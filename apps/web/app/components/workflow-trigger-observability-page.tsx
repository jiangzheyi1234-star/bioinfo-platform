"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { WorkflowPageHeader } from "./workflow-page-header";
import {
  createWorkflowTrigger,
  fetchWorkflowTriggerEvents,
  fetchWorkflowTriggerInboxEvents,
  fetchWorkflowTriggerReadinessObservation,
  fetchWorkflowTriggerSchedulerTicks,
  fetchWorkflowTriggers,
  replayWorkflowTriggerInboxEvent,
  runWorkflowTriggerSchedulerOnce,
  submitManualWorkflowTriggerEvent,
} from "./workflow-trigger-api";
import { WorkflowTriggerDefinitionControl } from "./workflow-trigger-definition-control";
import { WorkflowTriggerObservabilityPanel } from "./workflow-trigger-observability-panel";
import type {
  WorkflowTrigger,
  WorkflowTriggerDefinitionCreateRequest,
  WorkflowTriggerEvent,
  WorkflowTriggerInboxEvent,
  WorkflowTriggerReadinessObservation,
  WorkflowTriggerSchedulerTick,
} from "./workflow-trigger-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowTriggerObservabilityPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const triggerFromQuery = searchParams.get("trigger") || "";

  const [triggers, setTriggers] = useState<WorkflowTrigger[]>([]);
  const [events, setEvents] = useState<WorkflowTriggerEvent[]>([]);
  const [inboxEvents, setInboxEvents] = useState<WorkflowTriggerInboxEvent[]>([]);
  const [readinessObservation, setReadinessObservation] = useState<WorkflowTriggerReadinessObservation | null>(null);
  const [schedulerTicks, setSchedulerTicks] = useState<WorkflowTriggerSchedulerTick[]>([]);
  const [selectedTriggerId, setSelectedTriggerId] = useState(triggerFromQuery);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [inboxLoading, setInboxLoading] = useState(false);
  const [submittingManualTriggerId, setSubmittingManualTriggerId] = useState("");
  const [creatingTriggerDefinition, setCreatingTriggerDefinition] = useState(false);
  const [replayingInboxEventId, setReplayingInboxEventId] = useState("");
  const [runningScheduler, setRunningScheduler] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [eventError, setEventError] = useState("");

  const selectedTrigger = useMemo(
    () => triggers.find((trigger) => trigger.triggerId === selectedTriggerId) || null,
    [selectedTriggerId, triggers]
  );

  const loadTriggers = useCallback(async (forceRefresh = false) => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchWorkflowTriggers({ forceRefresh });
      setTriggers(data.items || []);
    } catch (err) {
      setError(workflowErrorMessage(err, "读取触发器失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEvents = useCallback(async (forceRefresh = false) => {
    if (!selectedTriggerId) {
      setEvents([]);
      return;
    }
    if (!forceRefresh) {
      setEventsLoading(true);
    }
    setEventError("");
    try {
      const data = await fetchWorkflowTriggerEvents(selectedTriggerId, { forceRefresh });
      setEvents(data.items || []);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "读取触发事件失败"));
    } finally {
      setEventsLoading(false);
    }
  }, [selectedTriggerId]);

  const loadInbox = useCallback(async (forceRefresh = false) => {
    if (!selectedTriggerId || selectedTrigger?.sourceType !== "webhook") {
      setInboxEvents([]);
      return;
    }
    if (!forceRefresh) {
      setInboxLoading(true);
    }
    setEventError("");
    try {
      const data = await fetchWorkflowTriggerInboxEvents(selectedTriggerId, { forceRefresh, limit: 100 });
      setInboxEvents(data.items || []);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "读取 webhook inbox 失败"));
    } finally {
      setInboxLoading(false);
    }
  }, [selectedTrigger?.sourceType, selectedTriggerId]);

  const loadReadinessObservation = useCallback(async (forceRefresh = false) => {
    if (!selectedTriggerId || !isReadinessSource(selectedTrigger?.sourceType)) {
      setReadinessObservation(null);
      return;
    }
    setEventError("");
    try {
      const data = await fetchWorkflowTriggerReadinessObservation(selectedTriggerId, { forceRefresh });
      setReadinessObservation(data.observation || null);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "读取 readiness observation 失败"));
    }
  }, [selectedTrigger?.sourceType, selectedTriggerId]);

  const loadSchedulerTicks = useCallback(async (forceRefresh = false) => {
    setEventError("");
    try {
      const data = await fetchWorkflowTriggerSchedulerTicks({ forceRefresh, limit: 20 });
      setSchedulerTicks(data.items || []);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "读取 scheduler ticks 失败"));
    }
  }, []);

  useEffect(() => {
    void loadTriggers();
  }, [loadTriggers]);

  useEffect(() => {
    void loadSchedulerTicks();
  }, [loadSchedulerTicks]);

  useEffect(() => {
    if (triggerFromQuery && triggerFromQuery !== selectedTriggerId) {
      setEvents([]);
      setInboxEvents([]);
      setReadinessObservation(null);
      setSelectedTriggerId(triggerFromQuery);
      return;
    }
    if (!selectedTriggerId && triggers[0]?.triggerId) {
      setEvents([]);
      setInboxEvents([]);
      setReadinessObservation(null);
      setSelectedTriggerId(triggers[0].triggerId);
    }
  }, [selectedTriggerId, triggerFromQuery, triggers]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    void loadInbox();
  }, [loadInbox]);

  useEffect(() => {
    void loadReadinessObservation();
  }, [loadReadinessObservation]);

  useEffect(() => {
    if (!selectedTriggerId) return;
    const timer = window.setInterval(() => {
      void loadEvents(true);
      void loadInbox(true);
      void loadReadinessObservation(true);
      void loadSchedulerTicks(true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [loadEvents, loadInbox, loadReadinessObservation, loadSchedulerTicks, selectedTriggerId]);

  function selectTrigger(triggerId: string) {
    setEvents([]);
    setInboxEvents([]);
    setReadinessObservation(null);
    setNotice("");
    setSelectedTriggerId(triggerId);
    const params = new URLSearchParams(searchParams.toString());
    params.set("trigger", triggerId);
    router.replace(`/workflows/results/triggers?${params.toString()}`, { scroll: false });
  }

  function refresh() {
    void loadTriggers(true);
    void loadEvents(true);
    void loadInbox(true);
    void loadReadinessObservation(true);
    void loadSchedulerTicks(true);
  }

  async function createTriggerDefinition(
    request: WorkflowTriggerDefinitionCreateRequest
  ): Promise<WorkflowTrigger | null> {
    if (creatingTriggerDefinition) return null;
    setCreatingTriggerDefinition(true);
    setError("");
    setEventError("");
    setNotice("");
    try {
      const created = await createWorkflowTrigger(request);
      const triggerId = created.triggerId;
      setNotice(`已创建 trigger definition ${created.name || triggerId}`);
      await loadTriggers(true);
      if (triggerId) {
        setEvents([]);
        setInboxEvents([]);
        setReadinessObservation(null);
        setSelectedTriggerId(triggerId);
        const params = new URLSearchParams(searchParams.toString());
        params.set("trigger", triggerId);
        router.replace(`/workflows/results/triggers?${params.toString()}`, { scroll: false });
      }
      return created;
    } catch (err) {
      setError(workflowErrorMessage(err, "创建触发定义失败"));
      return null;
    } finally {
      setCreatingTriggerDefinition(false);
    }
  }

  async function replayInboxEvent(inboxEventId: string) {
    if (!selectedTriggerId || !inboxEventId || replayingInboxEventId) return;
    setReplayingInboxEventId(inboxEventId);
    setEventError("");
    setNotice("");
    try {
      const result = await replayWorkflowTriggerInboxEvent(selectedTriggerId, inboxEventId);
      setNotice(result.run?.runId ? `已重放 inbox delivery，关联运行 ${result.run.runId}` : "已重放 inbox delivery");
      await Promise.all([loadEvents(true), loadInbox(true)]);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "重放 inbox delivery 失败"));
    } finally {
      setReplayingInboxEventId("");
    }
  }

  async function submitManualTrigger(triggerId: string) {
    if (!triggerId || submittingManualTriggerId) return;
    setSubmittingManualTriggerId(triggerId);
    setEventError("");
    setNotice("");
    try {
      const result = await submitManualWorkflowTriggerEvent(triggerId);
      setNotice(result.run?.runId ? `已提交 manual trigger，关联运行 ${result.run.runId}` : "已提交 manual trigger");
      await Promise.all([loadEvents(true), loadTriggers(true)]);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "提交 manual trigger 失败"));
    } finally {
      setSubmittingManualTriggerId("");
    }
  }

  async function runSchedulerOnce() {
    if (runningScheduler) return;
    setRunningScheduler(true);
    setEventError("");
    setNotice("");
    try {
      const result = await runWorkflowTriggerSchedulerOnce({ limit: 100 });
      setNotice(
        result.tickId
          ? `已执行 scheduler tick ${result.tickId}`
          : "已执行 scheduler tick"
      );
      await Promise.all([loadSchedulerTicks(true), loadEvents(true), loadTriggers(true)]);
    } catch (err) {
      setEventError(workflowErrorMessage(err, "运行 scheduler 失败"));
    } finally {
      setRunningScheduler(false);
    }
  }

  return (
    <div className="relative flex-1 h-full w-full overflow-y-auto bg-white px-8 py-10 text-slate-800">
      <div className="mx-auto max-w-6xl space-y-6">
        <WorkflowPageHeader
          title="触发器事件"
          leading={
            <Button asChild variant="outline" className="h-9 bg-white px-3 text-slate-600">
              <Link href="/workflows/results">
                <ArrowLeft strokeWidth={1.5} className="mr-2 h-4 w-4" />
                返回运行记录
              </Link>
            </Button>
          }
          actions={<span className="font-mono text-xs text-slate-400">{selectedTriggerId || "—"}</span>}
        />

        {loading && triggers.length === 0 && !error ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
            正在读取触发器
          </div>
        ) : error && triggers.length === 0 ? (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : (
          <>
            <WorkflowTriggerDefinitionControl
              creating={creatingTriggerDefinition}
              onCreate={createTriggerDefinition}
              serverIdHint={selectedTrigger?.serverId || triggers[0]?.serverId || ""}
            />
            <WorkflowTriggerObservabilityPanel
              error={error || eventError}
              events={events}
              eventsLoading={eventsLoading}
              inboxEvents={inboxEvents}
              inboxLoading={inboxLoading}
              loading={loading}
              notice={notice}
              onRefresh={refresh}
              onReplayInboxEvent={replayInboxEvent}
              onRunSchedulerOnce={runSchedulerOnce}
              onSelectTrigger={selectTrigger}
              onSubmitManualTrigger={submitManualTrigger}
              readinessObservation={readinessObservation}
              replayingInboxEventId={replayingInboxEventId}
              runningScheduler={runningScheduler}
              schedulerTicks={schedulerTicks}
              selectedTrigger={selectedTrigger}
              selectedTriggerId={selectedTriggerId}
              submittingManualTriggerId={submittingManualTriggerId}
              triggers={triggers}
            />
          </>
        )}
      </div>
    </div>
  );
}

function isReadinessSource(sourceType?: string) {
  return sourceType === "dataset" || sourceType === "file" || sourceType === "database_ready";
}
