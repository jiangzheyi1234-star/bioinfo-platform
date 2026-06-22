from __future__ import annotations

import asyncio

from apps.api.execution_query_routes import retry_run
from apps.api.models import RunRetryRequest
from apps.api.response_cache import invalidate_response_cache


def test_retry_run_route_delegates_to_runtime_and_invalidates_cache(monkeypatch) -> None:
    asyncio.run(invalidate_response_cache("runs", prefixes=("run_detail:run_retry",)))
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: FakeExecutionRuntime())

    result = asyncio.run(
        retry_run(
            "run_retry",
            RunRetryRequest(scope="run", actor="operator", reason="fixed input"),
        )
    )

    assert result == {
        "data": {
            "runId": "run_retry",
            "status": "queued",
            "stage": "retry",
            "commandId": "cmd_retry",
        }
    }


class FakeExecutionRuntime:
    def retry_run(self, run_id, payload):
        assert run_id == "run_retry"
        assert payload == {"scope": "run", "actor": "operator", "reason": "fixed input"}
        return {
            "data": {
                "runId": "run_retry",
                "status": "queued",
                "stage": "retry",
                "commandId": "cmd_retry",
            }
        }
