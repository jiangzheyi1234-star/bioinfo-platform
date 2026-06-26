"use client";

import { useMemo, useState } from "react";
import { Archive, Loader2, Pin, RefreshCw, ShieldCheck, XCircle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import {
  ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION,
  type WorkflowArtifactCacheEntry,
  type WorkflowArtifactCachePin,
} from "./workflow-artifact-cache-model";

const RETAIN_REASON = "web-ui-retain";
const RELEASE_REASON = "operator release";

export function WorkflowArtifactCachePanel({
  entries,
  error,
  loading,
  notice,
  onRefresh,
  onReleasePin,
  onRetainEntry,
  pins,
  releasingPinId,
  retainingEntryId,
}: {
  entries: WorkflowArtifactCacheEntry[];
  error: string;
  loading: boolean;
  notice: string;
  onRefresh: () => void;
  onReleasePin: (cachePinId: string, confirmation: string, reason: string) => void;
  onRetainEntry: (cacheEntryId: string, reason: string) => void;
  pins: WorkflowArtifactCachePin[];
  releasingPinId: string;
  retainingEntryId: string;
}) {
  const [retainTarget, setRetainTarget] = useState<WorkflowArtifactCacheEntry | null>(null);
  const [retainReason, setRetainReason] = useState(RETAIN_REASON);
  const [releaseTarget, setReleaseTarget] = useState<WorkflowArtifactCachePin | null>(null);
  const [releaseConfirmation, setReleaseConfirmation] = useState("");
  const [releaseReason, setReleaseReason] = useState(RELEASE_REASON);
  const activePolicyPins = useMemo(() => pins.filter(isActivePolicyPin), [pins]);
  const pinnedEntryIds = useMemo(
    () => new Set(activePolicyPins.map((pinItem) => pinItem.cacheEntryId).filter(Boolean)),
    [activePolicyPins]
  );

  function openRetainDialog(entry: WorkflowArtifactCacheEntry) {
    setRetainTarget(entry);
    setRetainReason(RETAIN_REASON);
  }

  function openReleaseDialog(pinItem: WorkflowArtifactCachePin) {
    setReleaseTarget(pinItem);
    setReleaseConfirmation("");
    setReleaseReason(RELEASE_REASON);
  }

  function closeRetainDialog(nextOpen: boolean) {
    if (!nextOpen) setRetainTarget(null);
  }

  function closeReleaseDialog(nextOpen: boolean) {
    if (!nextOpen) {
      setReleaseTarget(null);
      setReleaseConfirmation("");
    }
  }

  function confirmRetain() {
    if (!retainTarget || retainingEntryId) return;
    onRetainEntry(retainTarget.cacheEntryId, retainReason);
    setRetainTarget(null);
  }

  function confirmRelease() {
    if (!releaseTarget || releaseConfirmation.trim() !== ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION) return;
    onReleasePin(releaseTarget.cachePinId, releaseConfirmation, releaseReason);
    setReleaseTarget(null);
    setReleaseConfirmation("");
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-2">
          <Archive strokeWidth={1.5} className="h-4 w-4 text-slate-500" />
          <h2 className="text-sm font-semibold text-slate-900">Artifact cache</h2>
          <span className="text-xs text-slate-400">{entries.length} entries · {activePolicyPins.length} policy pins</span>
        </div>
        <Button
          type="button"
          variant="outline"
          className="h-8 bg-white px-2.5 text-xs text-slate-600"
          disabled={loading}
          onClick={onRefresh}
        >
          <RefreshCw strokeWidth={1.5} className={loading ? "mr-1.5 h-3.5 w-3.5 animate-spin" : "mr-1.5 h-3.5 w-3.5"} />
          刷新缓存
        </Button>
      </div>
      {notice ? (
        <div className="border-b border-emerald-100 bg-emerald-50 px-5 py-2 text-xs text-emerald-700">
          {notice}
        </div>
      ) : null}
      {error ? (
        <Alert variant="destructive" className="m-5">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}
      <div className="grid gap-5 p-5 xl:grid-cols-[1.35fr_0.65fr]">
        <CacheEntryList
          entries={entries}
          loading={loading}
          pinnedEntryIds={pinnedEntryIds}
          retainingEntryId={retainingEntryId}
          onRetain={openRetainDialog}
        />
        <PolicyPinList
          pins={activePolicyPins}
          releasingPinId={releasingPinId}
          onRelease={openReleaseDialog}
        />
      </div>
      <Dialog open={Boolean(retainTarget)} onOpenChange={closeRetainDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">保留缓存</DialogTitle>
            <DialogDescription className="text-xs">
              创建 operator policy pin 后，生命周期 GC 会把该缓存对象视为受保护对象。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <ReadonlyField label="Entry" value={retainTarget?.cacheEntryId} />
            <div>
              <Label htmlFor="artifact-cache-retain-reason" className="text-xs text-slate-500">
                Reason
              </Label>
              <Input
                id="artifact-cache-retain-reason"
                value={retainReason}
                onChange={(event) => setRetainReason(event.target.value)}
                className="h-8 text-xs"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" className="h-8 px-3 text-xs">
                取消
              </Button>
            </DialogClose>
            <Button
              type="button"
              className="h-8 bg-slate-900 px-3 text-xs text-white hover:bg-slate-800"
              disabled={!retainReason.trim() || Boolean(retainingEntryId)}
              onClick={confirmRetain}
            >
              创建 policy pin
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(releaseTarget)} onOpenChange={closeReleaseDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-base">释放 policy pin</DialogTitle>
            <DialogDescription className="text-xs">
              释放后，该缓存对象会重新服从生命周期 GC 策略。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <ReadonlyField label="Pin" value={releaseTarget?.cachePinId} />
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              输入 <span className="font-mono">{ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION}</span> 确认释放。
            </div>
            <Input
              value={releaseConfirmation}
              onChange={(event) => setReleaseConfirmation(event.target.value)}
              className="h-8 font-mono text-xs"
              placeholder={ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION}
            />
            <div>
              <Label htmlFor="artifact-cache-release-reason" className="text-xs text-slate-500">
                Reason
              </Label>
              <Input
                id="artifact-cache-release-reason"
                value={releaseReason}
                onChange={(event) => setReleaseReason(event.target.value)}
                className="h-8 text-xs"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" variant="ghost" className="h-8 px-3 text-xs">
                取消
              </Button>
            </DialogClose>
            <Button
              type="button"
              variant="destructive"
              className="h-8 px-3 text-xs"
              disabled={releaseConfirmation.trim() !== ARTIFACT_CACHE_POLICY_PIN_RELEASE_CONFIRMATION || Boolean(releasingPinId)}
              onClick={confirmRelease}
            >
              释放 pin
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function CacheEntryList({
  entries,
  loading,
  onRetain,
  pinnedEntryIds,
  retainingEntryId,
}: {
  entries: WorkflowArtifactCacheEntry[];
  loading: boolean;
  onRetain: (entry: WorkflowArtifactCacheEntry) => void;
  pinnedEntryIds: Set<string>;
  retainingEntryId: string;
}) {
  if (loading && entries.length === 0) {
    return <LoadingState label="正在读取 cache inventory" />;
  }
  if (entries.length === 0) {
    return <EmptyState label="暂无 cache entry" />;
  }
  return (
    <div className="space-y-3">
      {entries.slice(0, 12).map((entry) => {
        const active = entry.lifecycleState === "active";
        const pinned = pinnedEntryIds.has(entry.cacheEntryId);
        const retaining = retainingEntryId === entry.cacheEntryId;
        return (
          <article key={entry.cacheEntryId} className="rounded-lg border border-slate-200 px-3 py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-700">{entry.cacheEntryId || "—"}</span>
                  <StateBadge state={entry.lifecycleState} />
                  {pinned ? <StateBadge state="policy pinned" /> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-500">
                  <span>{entry.storageBackend || "backend: —"}</span>
                  <span>{formatBytes(entry.sizeBytes)}</span>
                  <span>{formatCount(entry.hitCount)} hits</span>
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-8 bg-white px-2.5 text-xs text-slate-600"
                disabled={!active || pinned || retaining}
                onClick={() => onRetain(entry)}
              >
                {retaining ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Pin strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
                {pinned ? "已保留" : "保留缓存"}
              </Button>
            </div>
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              <CacheField label="Blob" value={shortValue(entry.artifactBlobId)} />
              <CacheField label="Checksum" value={shortValue(entry.sha256)} />
              <CacheField label="Last used" value={formatDateTime(entry.lastUsedAt)} />
              <CacheField label="Cache fingerprint" value={entry.cacheKeyFingerprint || "—"} />
              <CacheField label="Revision fingerprint" value={entry.workflowRevisionFingerprint || "—"} />
              <CacheField label="Created" value={formatDateTime(entry.createdAt)} />
            </div>
          </article>
        );
      })}
      {entries.length > 12 ? (
        <div className="text-xs text-slate-400">另有 {entries.length - 12} 条 cache entry</div>
      ) : null}
    </div>
  );
}

function PolicyPinList({
  onRelease,
  pins,
  releasingPinId,
}: {
  onRelease: (pinItem: WorkflowArtifactCachePin) => void;
  pins: WorkflowArtifactCachePin[];
  releasingPinId: string;
}) {
  if (pins.length === 0) {
    return <EmptyState label="暂无 active policy pin" />;
  }
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
        <ShieldCheck strokeWidth={1.5} className="h-3.5 w-3.5" />
        Active policy pins
      </div>
      {pins.slice(0, 8).map((pinItem) => {
        const releasing = releasingPinId === pinItem.cachePinId;
        return (
          <article key={pinItem.cachePinId} className="rounded-lg border border-slate-200 px-3 py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-700">{pinItem.cachePinId || "—"}</span>
                  <StateBadge state={pinItem.state} />
                </div>
                <p className="mt-1 text-xs text-slate-600">{pinItem.reason || "—"}</p>
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-8 bg-white px-2.5 text-xs text-slate-600"
                disabled={!isActivePolicyPin(pinItem) || releasing}
                onClick={() => onRelease(pinItem)}
              >
                {releasing ? <Loader2 strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <XCircle strokeWidth={1.5} className="mr-1.5 h-3.5 w-3.5" />}
                释放 policy pin
              </Button>
            </div>
            <div className="mt-3 grid gap-2">
              <CacheField label="Entry" value={shortValue(pinItem.cacheEntryId)} />
              <CacheField label="Owner" value={`${pinItem.ownerKind || "operator"}:${pinItem.ownerId || "—"}`} />
              <CacheField label="Expires" value={formatDateTime(pinItem.expiresAt || undefined)} />
              <CacheField label="Created" value={formatDateTime(pinItem.createdAt)} />
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ReadonlyField({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 break-all font-mono text-xs text-slate-700">{value || "—"}</div>
    </div>
  );
}

function CacheField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="mt-1 break-all font-mono text-xs text-slate-700">{value}</div>
    </div>
  );
}

function StateBadge({ state }: { state?: string }) {
  const normalized = (state || "").toLowerCase();
  const active = normalized === "active" || normalized.includes("pinned");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[11px]",
        active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-600"
      )}
    >
      {state || "unknown"}
    </span>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div className="flex h-36 items-center justify-center rounded-lg border border-slate-100 text-sm text-slate-400">
      <Loader2 strokeWidth={1.5} className="mr-2 h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-lg border border-slate-100 px-4 py-10 text-center text-sm text-slate-400">{label}</div>;
}

function isActivePolicyPin(pinItem: WorkflowArtifactCachePin) {
  return (
    pinItem.pinScope === "policy" &&
    pinItem.ownerKind === "operator" &&
    pinItem.state === "active"
  );
}

function shortValue(value?: string | null) {
  const normalized = String(value || "").trim();
  if (!normalized) return "—";
  return normalized.length > 28 ? `${normalized.slice(0, 18)}...${normalized.slice(-8)}` : normalized;
}

function formatCount(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatBytes(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let current = Math.max(0, value);
  let unitIndex = 0;
  while (current >= 1024 && unitIndex < units.length - 1) {
    current /= 1024;
    unitIndex += 1;
  }
  const digits = current >= 10 || unitIndex === 0 ? 0 : 1;
  return `${current.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN");
}
