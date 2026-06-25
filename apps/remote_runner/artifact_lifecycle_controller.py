from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
import threading
from typing import Any

from .artifact_lifecycle_service import build_artifact_lifecycle_usage, preview_artifact_gc
from .config import RemoteRunnerConfig
from .config import load_remote_runner_config
from .evidence_storage import append_evidence_event
from .governance_audit import record_governance_audit_event
from .storage_core import get_connection, now_iso


LOGGER = logging.getLogger(__name__)
ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE = "artifact.lifecycle.controller_tick.v1"
ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA_NAME = "ArtifactLifecycleControllerTick"
ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA = "h2ometa.artifact-lifecycle-controller-tick.v1"
ARTIFACT_LIFECYCLE_CONTROLLER_MODE = "preview-only"
DEFAULT_CONTROLLER_REASON = "lifecycle_controller_preview"
DEFAULT_CONTROLLER_POLL_INTERVAL_SECONDS = 3600.0


@dataclass(frozen=True)
class ArtifactLifecycleControllerPolicy:
    retention_days: int
    eligible_run_statuses: tuple[str, ...]
    quota_bytes: int | None
    max_delete_bytes_per_tick: int | None
    reason: str
    actor: str


class ArtifactLifecycleControllerSupervisor:
    def __init__(
        self,
        cfg: RemoteRunnerConfig,
        *,
        poll_interval_seconds: float = DEFAULT_CONTROLLER_POLL_INTERVAL_SECONDS,
        policy_payload: dict[str, Any] | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_POLL_INTERVAL_INVALID")
        self._cfg = cfg
        self._poll_interval_seconds = poll_interval_seconds
        self._policy_payload = dict(policy_payload or {})
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="h2ometa-artifact-lifecycle-controller",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_artifact_lifecycle_controller_once(self._cfg, payload=self._policy_payload)
            except Exception:  # noqa: BLE001 - the preview controller should survive transient storage failures.
                LOGGER.exception("Artifact lifecycle controller preview tick failed.")
            self._stop_event.wait(self._poll_interval_seconds)


def run_artifact_lifecycle_controller_once(
    cfg: RemoteRunnerConfig,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluate_artifact_lifecycle_controller_tick(cfg, payload)


def start_artifact_lifecycle_controller_supervisor(
    cfg: RemoteRunnerConfig,
    *,
    poll_interval_seconds: float = DEFAULT_CONTROLLER_POLL_INTERVAL_SECONDS,
    policy_payload: dict[str, Any] | None = None,
) -> ArtifactLifecycleControllerSupervisor:
    supervisor = ArtifactLifecycleControllerSupervisor(
        cfg,
        poll_interval_seconds=poll_interval_seconds,
        policy_payload=policy_payload,
    )
    supervisor.start()
    return supervisor


def start_configured_artifact_lifecycle_controller_supervisor() -> ArtifactLifecycleControllerSupervisor | None:
    cfg = load_remote_runner_config()
    if not cfg.token or not _controller_enabled():
        return None
    return start_artifact_lifecycle_controller_supervisor(
        cfg,
        poll_interval_seconds=_configured_poll_interval_seconds(),
        policy_payload=_configured_policy_payload(),
    )


def evaluate_artifact_lifecycle_controller_tick(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = _controller_policy_from_payload(payload)
    evaluated_at = now_iso()
    usage = build_artifact_lifecycle_usage(cfg, quota_bytes=policy.quota_bytes)
    preview_payload = _preview_payload(policy)
    plan = preview_artifact_gc(cfg, preview_payload)
    tick = _controller_tick(
        evaluated_at=evaluated_at,
        policy=policy,
        usage=usage,
        plan=plan,
    )
    evidence = _record_controller_tick_evidence(cfg, tick)
    audit = record_governance_audit_event(
        cfg,
        action="artifact.lifecycle.controller_tick",
        subject_kind="artifact_lifecycle_controller",
        subject_id=tick["tickId"],
        actor=policy.actor,
        details={
            "planId": plan["planId"],
            "candidateCount": plan["candidateCount"],
            "deleteBytes": plan["deleteBytes"],
            "protectedCount": plan["protectedCount"],
            "quotaOverageBytes": tick["quotaOverageBytes"],
            "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
            "deleteConfirmationRequired": True,
            "policyDecision": tick["policyDecision"]["decision"],
            "policyReasonCode": tick["policyDecision"]["reasonCode"],
            "retentionHoldReasonCount": tick["retentionHolds"]["reasonCount"],
            "batchLimitApplied": tick["batchSafety"]["maxDeleteBytesApplied"],
        },
    )
    return {
        **tick,
        "evidenceId": evidence["eventId"],
        "governanceAuditEventId": audit["eventId"],
        "usage": usage,
    }


def _controller_policy_from_payload(payload: dict[str, Any] | None) -> ArtifactLifecycleControllerPolicy:
    body = dict(payload or {})
    statuses = tuple(
        sorted(
            {
                str(item or "").strip()
                for item in body.get("eligibleRunStatuses", ["completed", "failed", "canceled", "cancelled"])
                if str(item or "").strip()
            }
        )
    )
    if not statuses:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_STATUS_REQUIRED")
    quota = body.get("quotaBytes")
    max_delete = body.get("maxDeleteBytesPerTick")
    return ArtifactLifecycleControllerPolicy(
        retention_days=max(0, int(body.get("retentionDays", 30))),
        eligible_run_statuses=statuses,
        quota_bytes=max(0, int(quota)) if quota is not None else None,
        max_delete_bytes_per_tick=max(1, int(max_delete)) if max_delete is not None else None,
        reason=str(body.get("reason") or DEFAULT_CONTROLLER_REASON).strip() or DEFAULT_CONTROLLER_REASON,
        actor=str(body.get("actor") or "artifact-lifecycle-controller").strip() or "artifact-lifecycle-controller",
    )


def _preview_payload(policy: ArtifactLifecycleControllerPolicy) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "retentionDays": policy.retention_days,
        "eligibleRunStatuses": list(policy.eligible_run_statuses),
        "reason": policy.reason,
        "actor": policy.actor,
    }
    if policy.max_delete_bytes_per_tick is not None:
        payload["maxDeleteBytes"] = policy.max_delete_bytes_per_tick
    return payload


def _controller_tick(
    *,
    evaluated_at: str,
    policy: ArtifactLifecycleControllerPolicy,
    usage: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    quota_overage = _quota_overage_bytes(usage)
    policy_decision = _policy_decision(plan)
    retention_holds = _retention_hold_summary(plan)
    batch_safety = _batch_safety_summary(plan, policy=policy)
    summary = {
        "schemaVersion": ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA,
        "evaluatedAt": evaluated_at,
        "executionMode": ARTIFACT_LIFECYCLE_CONTROLLER_MODE,
        "deleteConfirmationRequired": True,
        "policy": {
            "retentionDays": policy.retention_days,
            "eligibleRunStatuses": list(policy.eligible_run_statuses),
            "quotaBytes": policy.quota_bytes,
            "maxDeleteBytesPerTick": policy.max_delete_bytes_per_tick,
            "reason": policy.reason,
        },
        "usage": {
            "activeBytes": usage["activeBytes"],
            "activeStorageObjectCount": usage["activeStorageObjectCount"],
            "quotaOverageBytes": quota_overage,
        },
        "policyDecision": policy_decision,
        "retentionHolds": retention_holds,
        "batchSafety": batch_safety,
        "gcPreview": {
            "planId": plan["planId"],
            "candidateCount": plan["candidateCount"],
            "deleteBytes": plan["deleteBytes"],
            "protectedCount": plan["protectedCount"],
            "protectedBytes": plan["protectedBytes"],
            "candidateArtifactCount": _artifact_count(plan["candidates"]),
            "candidateRunCount": _run_count(plan["candidates"]),
        },
    }
    return {
        **summary,
        "tickId": _tick_id(summary),
        "quotaOverageBytes": quota_overage,
        "wouldDeleteCount": plan["candidateCount"],
        "wouldDeleteBytes": plan["deleteBytes"],
    }


def _record_controller_tick_evidence(cfg: RemoteRunnerConfig, tick: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schemaVersion": tick["schemaVersion"],
        "tickId": tick["tickId"],
        "evaluatedAt": tick["evaluatedAt"],
        "executionMode": tick["executionMode"],
        "deleteConfirmationRequired": tick["deleteConfirmationRequired"],
        "policy": tick["policy"],
        "usage": tick["usage"],
        "policyDecision": tick["policyDecision"],
        "retentionHolds": tick["retentionHolds"],
        "batchSafety": tick["batchSafety"],
        "gcPreview": tick["gcPreview"],
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=ARTIFACT_LIFECYCLE_CONTROLLER_EVENT_TYPE,
            schema_name=ARTIFACT_LIFECYCLE_CONTROLLER_SCHEMA_NAME,
            subject_kind="artifact_lifecycle_controller",
            subject_id=tick["tickId"],
            payload=payload,
            producer="artifact_lifecycle_controller",
            occurred_at=str(tick["evaluatedAt"]),
        )
        connection.commit()
    return event


def _quota_overage_bytes(usage: dict[str, Any]) -> int:
    quota = usage.get("quota") if isinstance(usage.get("quota"), dict) else {}
    return max(0, int(quota.get("overageBytes") or 0))


def _policy_decision(plan: dict[str, Any]) -> dict[str, Any]:
    candidate_count = int(plan.get("candidateCount") or 0)
    delete_bytes = int(plan.get("deleteBytes") or 0)
    if candidate_count:
        decision = "preview_ready"
        reason_code = "DELETE_CONFIRMATION_REQUIRED"
        message = "GC candidates are available, but the controller is preview-only."
    else:
        decision = "no_action"
        reason_code = "NO_ELIGIBLE_CANDIDATES"
        message = "No artifact payloads are eligible for deletion under the current policy."
    return {
        "decision": decision,
        "reasonCode": reason_code,
        "message": message,
        "deletionAuthorized": False,
        "deleteConfirmationRequired": True,
        "candidateCount": candidate_count,
        "deleteBytes": delete_bytes,
    }


def _retention_hold_summary(plan: dict[str, Any]) -> dict[str, Any]:
    protected = [item for item in plan.get("protected") or [] if isinstance(item, dict)]
    reasons: dict[str, dict[str, Any]] = {}
    for item in protected:
        item_reasons = [str(reason or "").strip() for reason in item.get("reasons") or [] if str(reason or "").strip()]
        for reason in item_reasons or ["unspecified"]:
            summary = reasons.setdefault(
                reason,
                {
                    "reason": reason,
                    "groupCount": 0,
                    "artifactCount": 0,
                    "runCount": 0,
                    "bytes": 0,
                },
            )
            summary["groupCount"] += 1
            summary["artifactCount"] += len({str(value) for value in item.get("artifactIds") or [] if str(value or "").strip()})
            summary["runCount"] += len({str(value) for value in item.get("runIds") or [] if str(value or "").strip()})
            summary["bytes"] += int(item.get("sizeBytes") or 0)
    items = sorted(reasons.values(), key=lambda value: (-int(value["bytes"]), str(value["reason"])))
    return {
        "schemaVersion": "artifact-retention-hold-summary.v1",
        "protectedGroupCount": len(protected),
        "protectedBytes": int(plan.get("protectedBytes") or 0),
        "reasonCount": len(items),
        "reasons": items,
    }


def _batch_safety_summary(
    plan: dict[str, Any],
    *,
    policy: ArtifactLifecycleControllerPolicy,
) -> dict[str, Any]:
    candidate_count = int(plan.get("candidateCount") or 0)
    delete_bytes = int(plan.get("deleteBytes") or 0)
    protected = [item for item in plan.get("protected") or [] if isinstance(item, dict)]
    limited = [item for item in protected if "max_delete_bytes" in {str(reason) for reason in item.get("reasons") or []}]
    return {
        "schemaVersion": "artifact-gc-batch-safety.v1",
        "maxDeleteBytes": policy.max_delete_bytes_per_tick,
        "maxDeleteBytesApplied": policy.max_delete_bytes_per_tick is not None,
        "candidateCount": candidate_count,
        "candidateBytes": delete_bytes,
        "candidateArtifactCount": _artifact_count(plan.get("candidates") or []),
        "candidateRunCount": _run_count(plan.get("candidates") or []),
        "limitedGroupCount": len(limited),
        "limitedBytes": sum(int(item.get("sizeBytes") or 0) for item in limited),
    }


def _artifact_count(items: Any) -> int:
    artifact_ids = {
        str(artifact_id)
        for item in items or []
        if isinstance(item, dict)
        for artifact_id in item.get("artifactIds") or []
        if str(artifact_id or "").strip()
    }
    return len(artifact_ids)


def _run_count(items: Any) -> int:
    run_ids = {
        str(run_id)
        for item in items or []
        if isinstance(item, dict)
        for run_id in item.get("runIds") or []
        if str(run_id or "").strip()
    }
    return len(run_ids)


def _tick_id(summary: dict[str, Any]) -> str:
    return "alct_" + hashlib.sha256(_stable_json(summary).encode("utf-8")).hexdigest()[:24]


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _controller_enabled() -> bool:
    value = str(os.environ.get("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER", "0") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _configured_poll_interval_seconds() -> float:
    raw = str(os.environ.get("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_POLL_SECONDS", "") or "").strip()
    if not raw:
        return DEFAULT_CONTROLLER_POLL_INTERVAL_SECONDS
    value = float(raw)
    if value <= 0:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_POLL_INTERVAL_INVALID")
    return value


def _configured_policy_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "retentionDays": _configured_int("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_RETENTION_DAYS", default=30, minimum=0),
        "reason": _configured_str("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_REASON", DEFAULT_CONTROLLER_REASON),
        "actor": _configured_str("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_ACTOR", "artifact-lifecycle-controller"),
    }
    statuses = _configured_statuses()
    if statuses:
        payload["eligibleRunStatuses"] = statuses
    quota = _configured_optional_int("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_QUOTA_BYTES", minimum=0)
    if quota is not None:
        payload["quotaBytes"] = quota
    max_delete = _configured_optional_int("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_MAX_DELETE_BYTES_PER_TICK", minimum=1)
    if max_delete is not None:
        payload["maxDeleteBytesPerTick"] = max_delete
    return payload


def _configured_statuses() -> list[str]:
    raw = str(os.environ.get("H2OMETA_ARTIFACT_LIFECYCLE_CONTROLLER_STATUSES", "") or "").strip()
    if not raw:
        return []
    statuses = [item.strip() for item in raw.split(",") if item.strip()]
    if not statuses:
        raise ValueError("ARTIFACT_LIFECYCLE_CONTROLLER_STATUS_REQUIRED")
    return statuses


def _configured_int(name: str, *, default: int, minimum: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    value = int(raw) if raw else default
    if value < minimum:
        raise ValueError(f"{name}_INVALID")
    return value


def _configured_optional_int(name: str, *, minimum: int) -> int | None:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return None
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name}_INVALID")
    return value


def _configured_str(name: str, default: str) -> str:
    return str(os.environ.get(name, "") or default).strip() or default
