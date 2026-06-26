from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .secret_provider import SecretProviderError, parse_secret_ref


_SECRET_REF_PURPOSE = "webhook-signing-secret"
TRIGGER_READ_SCHEMA_VERSION = "workflow-trigger-read.v1"
TRIGGER_LIST_SCHEMA_VERSION = "workflow-trigger-list.v1"
_READINESS_SOURCE_TYPES = frozenset({"dataset", "file", "database_ready"})
_AUTHORITATIVE_INGRESS_BY_SOURCE = {
    "manual": "manual-event-api",
    "cron": "cron-scheduler",
    "webhook": "webhook-inbox",
    "backfill": "backfill-launch",
}
_BLOCKER_BY_SOURCE = {
    "cron": "cron-scheduler-owned",
    "webhook": "webhook-inbox-owned",
    "backfill": "backfill-launch-owned",
}
_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "apikey",
        "accesskey",
        "authorization",
        "bearer",
        "clientsecret",
        "identityref",
        "inlinesecret",
        "keyfile",
        "password",
        "privatekey",
        "secret",
        "secretvalue",
        "signingsecret",
        "token",
        "webhooksecret",
    }
)


@dataclass(frozen=True)
class TriggerSpecRedaction:
    path: str
    reason: Literal["secret-ref", "secret-like-field"]
    ref_hash: str | None = None
    scheme: str | None = None
    provider_kind: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "reason": self.reason,
            **({"refHash": self.ref_hash} if self.ref_hash else {}),
            **({"scheme": self.scheme} if self.scheme else {}),
            **({"providerKind": self.provider_kind} if self.provider_kind else {}),
            **({"purpose": _SECRET_REF_PURPOSE} if self.reason == "secret-ref" and self.ref_hash else {}),
        }


def trigger_for_read_model(trigger: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(trigger)
    data["schemaVersion"] = TRIGGER_READ_SCHEMA_VERSION
    data["triggerContract"] = _trigger_contract_for_read(data)
    trigger_spec = data.get("triggerSpec")
    if isinstance(trigger_spec, Mapping):
        redactions: list[TriggerSpecRedaction] = []
        data["triggerSpec"] = redact_trigger_spec_for_read(trigger_spec, redactions=redactions)
        if redactions:
            data["triggerSpecRedactions"] = [item.to_dict() for item in redactions]
    run_spec = data.get("runSpec")
    if isinstance(run_spec, Mapping):
        redactions = []
        data["runSpec"] = redact_trigger_spec_for_read(run_spec, redactions=redactions, root_path="runSpec")
        if redactions:
            data["runSpecRedactions"] = [item.to_dict() for item in redactions]
    return data


def trigger_list_for_read_model(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    data["schemaVersion"] = TRIGGER_LIST_SCHEMA_VERSION
    items = data.get("items")
    if isinstance(items, list):
        data["items"] = [trigger_for_read_model(item) if isinstance(item, Mapping) else item for item in items]
    return data


def _trigger_contract_for_read(trigger: Mapping[str, Any]) -> dict[str, object]:
    source_type = str(trigger.get("sourceType") or "").strip()
    enabled = bool(trigger.get("enabled"))
    authoritative_ingress = _authoritative_ingress(source_type)
    blockers: list[str] = []
    actions: list[str] = []
    if not enabled:
        blockers.append("trigger-disabled")
    elif source_type == "manual":
        actions.append("submit-manual-event")
    elif source_type == "backfill":
        actions.append("preview-backfill")
        blockers.append(_BLOCKER_BY_SOURCE[source_type])
    elif source_type in _BLOCKER_BY_SOURCE:
        blockers.append(_BLOCKER_BY_SOURCE[source_type])
    elif source_type in _READINESS_SOURCE_TYPES:
        blockers.append("readiness-api-owned")
    else:
        blockers.append("unknown-trigger-source")
    return {
        "schemaVersion": "workflow-trigger-contract.v1",
        "sourceType": source_type or "unknown",
        "authoritativeIngress": authoritative_ingress,
        "provenanceStamped": True,
        "immutableTriggerEventRequired": True,
        "rawPayloadExported": False,
        "supportedOperatorActions": actions,
        "blockers": blockers,
    }


def _authoritative_ingress(source_type: str) -> str:
    if source_type in _READINESS_SOURCE_TYPES:
        return "readiness-api"
    return _AUTHORITATIVE_INGRESS_BY_SOURCE.get(source_type, "unsupported")


def redact_trigger_spec_for_read(
    trigger_spec: Mapping[str, Any],
    *,
    redactions: list[TriggerSpecRedaction] | None = None,
    root_path: str = "triggerSpec",
) -> dict[str, Any]:
    redaction_list = redactions if redactions is not None else []
    redacted = _redact_value(trigger_spec, path=root_path, redactions=redaction_list)
    if not isinstance(redacted, dict):
        raise ValueError("WORKFLOW_TRIGGER_SPEC_READ_MODEL_INVALID")
    return redacted


def _redact_value(value: Any, *, path: str, redactions: list[TriggerSpecRedaction]) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            token = _key_token(key)
            if token == "secretref":
                result[key] = _redacted_secret_ref(child, path=child_path, redactions=redactions)
            elif token in _SENSITIVE_KEY_TOKENS:
                redactions.append(TriggerSpecRedaction(path=child_path, reason="secret-like-field"))
                result[key] = {"redacted": True, "reason": "secret-like-field"}
            else:
                result[key] = _redact_value(child, path=child_path, redactions=redactions)
        return result
    if isinstance(value, list):
        return [_redact_value(item, path=f"{path}[{index}]", redactions=redactions) for index, item in enumerate(value)]
    return value


def _redacted_secret_ref(
    value: object,
    *,
    path: str,
    redactions: list[TriggerSpecRedaction],
) -> dict[str, object]:
    text = str(value or "").strip()
    try:
        descriptor = parse_secret_ref(text, purpose=_SECRET_REF_PURPOSE)
        ref_hash = descriptor.ref_hash
        scheme = descriptor.scheme
        provider_kind = descriptor.provider_kind
    except SecretProviderError:
        ref_hash = None
        scheme = None
        provider_kind = None
    redactions.append(
        TriggerSpecRedaction(
            path=path,
            reason="secret-ref",
            ref_hash=ref_hash,
            scheme=scheme,
            provider_kind=provider_kind,
        )
    )
    return {
        "redacted": True,
        "reason": "secret-ref",
        **({"refHash": ref_hash} if ref_hash else {}),
        **({"scheme": scheme} if scheme else {}),
        **({"providerKind": provider_kind} if provider_kind else {}),
        **({"purpose": _SECRET_REF_PURPOSE} if ref_hash else {}),
    }


def _key_token(key: str) -> str:
    return "".join(character for character in key.lower() if character.isalnum())
