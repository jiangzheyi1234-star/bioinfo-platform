"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Loader2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { WorkflowPageHeader } from "./workflow-page-header";
import { fetchWorkflowTriggerEvents, fetchWorkflowTriggers } from "./workflow-trigger-api";
import { WorkflowTriggerObservabilityPanel } from "./workflow-trigger-observability-panel";
import type { WorkflowTrigger, WorkflowTriggerEvent } from "./workflow-trigger-model";
import { workflowErrorMessage } from "./workflows-page-model";

export function WorkflowTriggerObservabilityPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const triggerFromQuery = searchParams.get("trigger") || "";

  const [triggers, setTriggers] = useState<WorkflowTrigger[]>([]);
  const [events, setEvents] = useState<WorkflowTriggerEvent[]>([]);
  const [selectedTriggerId, setSelectedTriggerId] = useState(triggerFromQuery);
  const [loading, setLoading] = useState(true);
  const [eventsLoading, setEventsLoading] = useState(false);
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

  useEffect(() => {
    void loadTriggers();
  }, [loadTriggers]);

  useEffect(() => {
    if (triggerFromQuery && triggerFromQuery !== selectedTriggerId) {
      setEvents([]);
      setSelectedTriggerId(triggerFromQuery);
      return;
    }
    if (!selectedTriggerId && triggers[0]?.triggerId) {
      setEvents([]);
      setSelectedTriggerId(triggers[0].triggerId);
    }
  }, [selectedTriggerId, triggerFromQuery, triggers]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  useEffect(() => {
    if (!selectedTriggerId) return;
    const timer = window.setInterval(() => void loadEvents(true), 5000);
    return () => window.clearInterval(timer);
  }, [loadEvents, selectedTriggerId]);

  function selectTrigger(triggerId: string) {
    setEvents([]);
    setSelectedTriggerId(triggerId);
    const params = new URLSearchParams(searchParams.toString());
    params.set("trigger", triggerId);
    router.replace(`/workflows/results/triggers?${params.toString()}`, { scroll: false });
  }

  function refresh() {
    void loadTriggers(true);
    void loadEvents(true);
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
          <WorkflowTriggerObservabilityPanel
            error={error || eventError}
            events={events}
            eventsLoading={eventsLoading}
            loading={loading}
            onRefresh={refresh}
            onSelectTrigger={selectTrigger}
            selectedTrigger={selectedTrigger}
            selectedTriggerId={selectedTriggerId}
            triggers={triggers}
          />
        )}
      </div>
    </div>
  );
}
