from __future__ import annotations

import asyncio

from apps.api.execution_query_routes import get_run_attempts


def test_local_run_attempt_route_preserves_runtime_wrapper(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: FakeAttemptRuntime())

    response = asyncio.run(get_run_attempts("run_attempt_contract"))

    assert response == {
        "data": {
            "schemaVersion": "run-attempts.v1",
            "runId": "run_attempt_contract",
            "attempts": [{"attemptId": "att_contract", "state": "running"}],
        }
    }


class FakeAttemptRuntime:
    def get_run_attempts(self, run_id: str):
        assert run_id == "run_attempt_contract"
        return {
            "data": {
                "schemaVersion": "run-attempts.v1",
                "runId": run_id,
                "attempts": [{"attemptId": "att_contract", "state": "running"}],
            }
        }
