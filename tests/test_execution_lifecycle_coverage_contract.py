from __future__ import annotations

import asyncio
from typing import Any

import pytest

import core.remote_runner.proxy as proxy_module
import apps.remote_runner.execution_lifecycle_service as lifecycle_service_module
from apps.remote_runner.api_models import ExecutionLifecycleGuardRequest
from apps.remote_runner.errors import RemoteRunnerOperationBlockedError
from apps.remote_runner.execution_lifecycle_guard import EXECUTION_LIFECYCLE_QUIESCENCE_COVERAGE
from core.contracts.execution_activity import (
    EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
    EXECUTION_LIFECYCLE_REQUIRED_QUIESCENCE_COVERAGE,
    require_execution_lifecycle_guard_success_contract,
    require_execution_lifecycle_quiescence_coverage,
)
from core.contracts.remote_endpoints import EXECUTION_LIFECYCLE_GUARD, EXECUTION_LIFECYCLE_GUARD_RELEASE
from core.remote_runner.client import RemoteRunnerConflictError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.proxy import RemoteRunnerProxyMixin


PARTIAL_PRODUCER_COVERAGE = ("run-execution",)
FULL_REQUIRED_COVERAGE = (
    "run-execution",
    "tool-preparation",
    "workflow-automation",
    "mutating-operations",
)
GUARD_REQUEST = {
    "action": "upgrade",
    "owner": "bootstrap-operation-1",
    "ttlSeconds": 600,
}


def test_interim_lifecycle_guard_declares_only_implemented_quiescence_coverage() -> None:
    assert tuple(EXECUTION_LIFECYCLE_QUIESCENCE_COVERAGE) == PARTIAL_PRODUCER_COVERAGE
    assert EXECUTION_LIFECYCLE_REQUIRED_QUIESCENCE_COVERAGE == FULL_REQUIRED_COVERAGE
    assert set(EXECUTION_LIFECYCLE_QUIESCENCE_COVERAGE) < set(
        EXECUTION_LIFECYCLE_REQUIRED_QUIESCENCE_COVERAGE
    )


def test_http_lifecycle_guard_rejects_partial_coverage_before_storage_mutation(monkeypatch) -> None:
    storage_calls: list[dict[str, Any]] = []
    audit_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        lifecycle_service_module,
        "_authorized_lifecycle_guard_config",
        lambda _authorization: object(),
    )
    monkeypatch.setattr(
        lifecycle_service_module,
        "request_execution_lifecycle_guard",
        lambda _cfg, **kwargs: storage_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        lifecycle_service_module,
        "_record_lifecycle_audit",
        lambda _cfg, **kwargs: audit_calls.append(dict(kwargs)),
    )

    with pytest.raises(RemoteRunnerOperationBlockedError) as blocked:
        asyncio.run(
            lifecycle_service_module.request_execution_lifecycle_guard_from_request(
                ExecutionLifecycleGuardRequest(**GUARD_REQUEST),
                None,
            )
        )

    assert storage_calls == []
    assert blocked.value.payload["maintenanceActive"] is False
    assert blocked.value.payload["quiescenceCoverage"] == list(PARTIAL_PRODUCER_COVERAGE)
    assert blocked.value.payload["missingQuiescenceCoverage"] == [
        "tool-preparation",
        "workflow-automation",
        "mutating-operations",
    ]
    assert audit_calls[0]["decision"] == "deny"


def test_lifecycle_coverage_consumer_rejects_partial_coverage() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "quiescence coverage is incomplete: tool-preparation, "
            "workflow-automation, mutating-operations"
        ),
    ):
        require_execution_lifecycle_quiescence_coverage(
            {"quiescenceCoverage": list(PARTIAL_PRODUCER_COVERAGE)},
            make_error=ValueError,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"quiescenceCoverage": None},
        {"quiescenceCoverage": PARTIAL_PRODUCER_COVERAGE},
        {"quiescenceCoverage": ["run-execution", 1]},
        {"quiescenceCoverage": [""]},
    ],
)
def test_lifecycle_coverage_consumer_rejects_malformed_coverage(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="quiescenceCoverage is invalid"):
        require_execution_lifecycle_quiescence_coverage(payload, make_error=ValueError)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schemaVersion": "execution-lifecycle-guard.v2"}, "schemaVersion is invalid"),
        ({"owner": "another-owner"}, "identity does not match"),
        ({"maintenanceActive": False}, "did not attest active idle maintenance"),
        ({"expiryPolicy": "auto-open"}, "expiryPolicy is not fail-closed"),
        ({"expiresAt": "2099-06-07T09:59:59Z"}, "expiresAt must be after requestedAt"),
        ({"blockReasons": ["claimed-jobs"]}, "blockReasons must be an empty list"),
        ({"claimedJobCount": True}, "claimedJobCount is not a non-negative integer"),
    ],
)
def test_lifecycle_success_contract_rejects_malformed_attestation(
    changes: dict[str, Any],
    message: str,
) -> None:
    payload = _guard_success_payload(coverage=FULL_REQUIRED_COVERAGE)
    payload.update(changes)

    with pytest.raises(ValueError, match=message):
        require_execution_lifecycle_guard_success_contract(
            payload,
            expected_action=GUARD_REQUEST["action"],
            expected_owner=GUARD_REQUEST["owner"],
            make_error=ValueError,
        )


def test_proxy_releases_successful_guard_when_coverage_validation_fails(monkeypatch) -> None:
    client = object()
    calls: list[tuple[object, str, dict[str, Any]]] = []

    def fake_execute_remote_endpoint(
        actual_client,
        endpoint_id: str,
        *,
        path_values: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        assert path_values == {}
        calls.append((actual_client, endpoint_id, dict(payload)))
        if endpoint_id == EXECUTION_LIFECYCLE_GUARD:
            return _guard_success_payload(coverage=PARTIAL_PRODUCER_COVERAGE)
        assert endpoint_id == EXECUTION_LIFECYCLE_GUARD_RELEASE
        return {
            "schemaVersion": EXECUTION_LIFECYCLE_GUARD_RELEASE_SCHEMA_VERSION,
            "action": GUARD_REQUEST["action"],
            "owner": GUARD_REQUEST["owner"],
            "released": True,
            "previous": {"active": True},
        }

    monkeypatch.setattr(proxy_module, "execute_remote_endpoint", fake_execute_remote_endpoint)

    with pytest.raises(RemoteRunnerManagerError, match="quiescence coverage is incomplete") as raised:
        RemoteRunnerProxyMixin._call_lifecycle_guard_endpoint_with_client(
            client=client,
            endpoint_id=EXECUTION_LIFECYCLE_GUARD,
            payload=dict(GUARD_REQUEST),
        )

    assert calls == [
        (client, EXECUTION_LIFECYCLE_GUARD, GUARD_REQUEST),
        (
            client,
            EXECUTION_LIFECYCLE_GUARD_RELEASE,
            {"action": GUARD_REQUEST["action"], "owner": GUARD_REQUEST["owner"]},
        ),
    ]
    assert raised.value.detail["recoveryRequired"] is False
    assert raised.value.detail["maintenanceRelease"]["ok"] is True


def test_proxy_marks_recovery_required_when_partial_guard_cleanup_fails(monkeypatch) -> None:
    def fake_execute_remote_endpoint(_client, endpoint_id: str, **_kwargs) -> dict[str, Any]:
        if endpoint_id == EXECUTION_LIFECYCLE_GUARD:
            return _guard_success_payload(coverage=PARTIAL_PRODUCER_COVERAGE)
        raise RuntimeError("release transport failed")

    monkeypatch.setattr(proxy_module, "execute_remote_endpoint", fake_execute_remote_endpoint)

    with pytest.raises(RemoteRunnerManagerError) as raised:
        RemoteRunnerProxyMixin._call_lifecycle_guard_endpoint_with_client(
            client=object(),
            endpoint_id=EXECUTION_LIFECYCLE_GUARD,
            payload=dict(GUARD_REQUEST),
        )

    assert raised.value.detail["recoveryRequired"] is True
    assert raised.value.detail["maintenanceRelease"] == {
        "ok": False,
        "reasonCode": "EXECUTION_LIFECYCLE_GUARD_RELEASE_FAILED",
        "message": "release transport failed",
    }


def test_proxy_rejects_partial_coverage_on_busy_guard_without_releasing(monkeypatch) -> None:
    busy_payload = {
        "blockReasons": ["active-workflow-leases"],
        "quiescenceCoverage": list(PARTIAL_PRODUCER_COVERAGE),
        "maintenanceActive": False,
    }
    calls: list[str] = []

    def fake_execute_remote_endpoint(_client, endpoint_id: str, **_kwargs) -> dict[str, Any]:
        calls.append(endpoint_id)
        raise RemoteRunnerConflictError(busy_payload)

    monkeypatch.setattr(proxy_module, "execute_remote_endpoint", fake_execute_remote_endpoint)

    with pytest.raises(RemoteRunnerManagerError, match="quiescence coverage is incomplete"):
        RemoteRunnerProxyMixin._call_lifecycle_guard_endpoint_with_client(
            client=object(),
            endpoint_id=EXECUTION_LIFECYCLE_GUARD,
            payload=dict(GUARD_REQUEST),
        )

    assert calls == [EXECUTION_LIFECYCLE_GUARD]


def test_proxy_preserves_owner_conflict_payload_without_coverage_validation(monkeypatch) -> None:
    conflict_payload = {
        "reasonCode": "EXECUTION_LIFECYCLE_GUARD_ALREADY_ACTIVE",
        "requestedAction": "upgrade",
        "requestedOwner": "bootstrap-operation-2",
        "activeAction": "upgrade",
        "activeOwner": "bootstrap-operation-1",
    }
    calls: list[str] = []

    def fake_execute_remote_endpoint(_client, endpoint_id: str, **_kwargs) -> dict[str, Any]:
        calls.append(endpoint_id)
        raise RemoteRunnerConflictError(conflict_payload)

    monkeypatch.setattr(proxy_module, "execute_remote_endpoint", fake_execute_remote_endpoint)

    with pytest.raises(RemoteRunnerManagerError, match="lifecycle guard blocked") as raised:
        RemoteRunnerProxyMixin._call_lifecycle_guard_endpoint_with_client(
            client=object(),
            endpoint_id=EXECUTION_LIFECYCLE_GUARD,
            payload=dict(GUARD_REQUEST),
        )

    assert raised.value.status_code == 409
    assert raised.value.detail is conflict_payload
    assert calls == [EXECUTION_LIFECYCLE_GUARD]


def _guard_success_payload(*, coverage: tuple[str, ...]) -> dict[str, Any]:
    return {
        "schemaVersion": EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION,
        "action": GUARD_REQUEST["action"],
        "owner": GUARD_REQUEST["owner"],
        "idle": True,
        "maintenanceActive": True,
        "requestedAt": "2099-06-07T10:00:00Z",
        "expiresAt": "2099-06-07T10:10:00Z",
        "expiryPolicy": "fail-closed",
        "quiescenceCoverage": list(coverage),
        "blockReasons": [],
        "activeWorkerCount": 0,
        "drainRequestedWorkerCount": 0,
        "activeLeaseCount": 0,
        "allocatedResourceCount": 0,
        "resourceWaitCount": 0,
        "queuedJobCount": 0,
        "claimedJobCount": 0,
        "runningSlotCount": 0,
        "queuedToolPrepareJobCount": 0,
        "runningToolPrepareJobCount": 0,
        "activeToolPrepareClaimCount": 0,
    }
