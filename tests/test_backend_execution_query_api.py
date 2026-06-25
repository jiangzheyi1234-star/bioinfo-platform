from __future__ import annotations

import asyncio

from apps.api.execution_query_routes import resume_run, retry_run, retry_run_rules
from apps.api.models import RunResumeRequest, RunRetryRequest, RunRuleRetryRequest
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


def test_retry_run_rules_route_delegates_fail_closed_runtime_result(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        retry_run_rules(
            "run_rule_retry",
            RunRuleRetryRequest(
                confirmation="retry-failed-rules",
                planHash="a" * 64,
                actor="operator",
                reason="reviewed failure locator",
            ),
        )
    )

    assert runtime.rule_retry_calls == [
        (
            "run_rule_retry",
            {
                "confirmation": "retry-failed-rules",
                "planHash": "a" * 64,
                "actor": "operator",
                "reason": "reviewed failure locator",
            },
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "run-rule-retry-result.v1",
            "runId": "run_rule_retry",
            "accepted": False,
            "blocked": True,
            "reasonCode": "RULE_RETRY_MUTATION_API_DISABLED",
        }
    }


def test_resume_run_route_delegates_fail_closed_runtime_result(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        resume_run(
            "run_resume",
            RunResumeRequest(
                confirmation="resume-run",
                planHash="b" * 64,
                actor="operator",
                reason="reviewed resume plan",
            ),
        )
    )

    assert runtime.resume_calls == [
        (
            "run_resume",
            {
                "confirmation": "resume-run",
                "planHash": "b" * 64,
                "actor": "operator",
                "reason": "reviewed resume plan",
            },
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "run-resume-result.v1",
            "runId": "run_resume",
            "accepted": False,
            "blocked": True,
            "reasonCode": "RUN_RESUME_MUTATION_API_DISABLED",
        }
    }


class FakeExecutionRuntime:
    def __init__(self) -> None:
        self.rule_retry_calls = []
        self.resume_calls = []

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

    def retry_run_rules(self, run_id, payload):
        self.rule_retry_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "run-rule-retry-result.v1",
                "runId": run_id,
                "accepted": False,
                "blocked": True,
                "reasonCode": "RULE_RETRY_MUTATION_API_DISABLED",
            }
        }

    def resume_run(self, run_id, payload):
        self.resume_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "run-resume-result.v1",
                "runId": run_id,
                "accepted": False,
                "blocked": True,
                "reasonCode": "RUN_RESUME_MUTATION_API_DISABLED",
            }
        }
