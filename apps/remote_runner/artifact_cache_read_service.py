from __future__ import annotations

import hashlib
import json
from typing import Any

from .artifact_cache_pin_service import list_artifact_cache_policy_pins
from .artifact_cache_storage import list_artifact_cache_entries, lookup_artifact_cache_entry
from .config import RemoteRunnerConfig
from .governance_audit import record_governance_audit_event


def list_governed_artifact_cache_entries(
    cfg: RemoteRunnerConfig,
    *,
    workflow_revision_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    entries = list_artifact_cache_entries(cfg, workflow_revision_id=workflow_revision_id, limit=limit)
    public = {
        "schemaVersion": "artifact-cache-entries-public.v1",
        "redactionPolicy": _cache_redaction_policy(),
        "items": [public_artifact_cache_record(item) for item in entries.get("items") or []],
    }
    record_governance_audit_event(
        cfg,
        action="artifact.cache.entries.read",
        subject_kind="artifact_cache",
        subject_id="query",
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "filteredByWorkflowRevision": bool(str(workflow_revision_id or "").strip()),
            "limit": _bounded_limit(limit),
            "returnedCount": len(entries.get("items") or []),
        },
    )
    return public


def list_governed_artifact_cache_pins(
    cfg: RemoteRunnerConfig,
    *,
    cache_entry_id: str | None = None,
    state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    pins = list_artifact_cache_policy_pins(cfg, cache_entry_id=cache_entry_id, state=state, limit=limit)
    public = {
        "schemaVersion": "artifact-cache-pins-public.v1",
        "redactionPolicy": _cache_redaction_policy(),
        "items": [public_artifact_cache_record(item) for item in pins.get("items") or []],
    }
    record_governance_audit_event(
        cfg,
        action="artifact.cache_pins.read",
        subject_kind="artifact_cache_pin",
        subject_id="query",
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "filteredByCacheEntry": bool(str(cache_entry_id or "").strip()),
            "filteredByState": bool(str(state or "").strip()),
            "limit": _bounded_limit(limit),
            "returnedCount": len(pins.get("items") or []),
        },
    )
    return public


def lookup_governed_artifact_cache_entry(
    cfg: RemoteRunnerConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    result = lookup_artifact_cache_entry(cfg, payload)
    entry = result.get("entry") if isinstance(result.get("entry"), dict) else {}
    record_governance_audit_event(
        cfg,
        action="artifact.cache.lookup",
        subject_kind="artifact_cache",
        subject_id=str(entry.get("cacheEntryId") or "lookup"),
        actor=cfg.api_token_actor or "remote-runner-api",
        details={
            "hit": bool(result.get("hit")),
            "reason": str(result.get("reason") or ""),
            "workflowRevisionProvided": bool(str(payload.get("workflowRevisionId") or "").strip()),
            "selectorProvided": bool(str(payload.get("artifactKey") or "").strip()),
            "stepSelectorProvided": bool(str(payload.get("stepId") or "").strip()),
            "inputCount": _collection_size(payload.get("inputs")),
            "hasParams": bool(payload.get("params")),
            "hasResourceBindings": bool(payload.get("resourceBindings")),
            "hasExecutionOptions": bool(payload.get("execution")),
            "lookupEvidenceRecorded": bool(str(result.get("evidenceId") or "").strip()),
        },
    )
    return _public_lookup_result(result)


def _public_lookup_result(result: dict[str, Any]) -> dict[str, Any]:
    public = {
        "schemaVersion": "artifact-cache-lookup-public.v1",
        "hit": bool(result.get("hit")),
        "reason": str(result.get("reason") or ""),
        "evidenceId": result.get("evidenceId"),
        "lookedUpAt": result.get("lookedUpAt"),
        "keySummary": _public_key_payload_summary(result.get("keyPayload")),
        "redactionPolicy": _cache_redaction_policy(),
    }
    entry = result.get("entry")
    if isinstance(entry, dict):
        public["entry"] = public_artifact_cache_record(entry)
    return public


def public_artifact_cache_record(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    cache_key = str(public.get("cacheKey") or "")
    workflow_revision_id = str(public.get("workflowRevisionId") or "")
    if cache_key:
        public["cacheKeyFingerprint"] = _short_digest(cache_key)
    if workflow_revision_id:
        public["workflowRevisionFingerprint"] = _short_digest(workflow_revision_id)
    for key in (
        "artifactKey",
        "cacheKey",
        "keyPayload",
        "stepId",
        "storageUri",
        "workflowRevisionId",
    ):
        public.pop(key, None)
    return public


def _public_key_payload_summary(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "schemaVersion": "artifact-cache-key-summary-public.v1",
        "keyPayloadFingerprint": _short_digest(_stable_json(payload)) if payload else "",
        "workflowRevisionProvided": bool(str(payload.get("workflowRevisionId") or "").strip()),
        "artifactSelectorProvided": bool(str(payload.get("artifactKey") or "").strip()),
        "stepSelectorProvided": bool(str(payload.get("stepId") or "").strip()),
        "roleProvided": bool(str(payload.get("role") or "").strip()),
        "inputDigestProvided": bool(str(payload.get("inputDigest") or "").strip()),
        "paramsDigestProvided": bool(str(payload.get("paramsDigest") or "").strip()),
        "resourceBindingsDigestProvided": bool(str(payload.get("resourceBindingsDigest") or "").strip()),
        "executionDigestProvided": bool(str(payload.get("executionDigest") or "").strip()),
    }


def _cache_redaction_policy() -> dict[str, bool]:
    return {
        "cacheKeysExposed": False,
        "keyPayloadsExposed": False,
        "workflowRevisionIdsExposed": False,
        "artifactSelectorsExposed": False,
        "storageUrisExposed": False,
    }


def _short_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _stable_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _bounded_limit(value: int) -> int:
    return min(500, max(1, int(value)))


def _collection_size(value: Any) -> int:
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    return 0
