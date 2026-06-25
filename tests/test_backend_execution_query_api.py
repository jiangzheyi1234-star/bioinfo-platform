from __future__ import annotations

import asyncio

from apps.api.execution_query_routes import (
    apply_rule_cache_restore_adoption,
    apply_rule_cache_restore_final_outputs,
    apply_rule_output_invalidation,
    apply_rule_cache_restore_staged_files,
    prepare_rule_cache_restore_adoption,
    prepare_rule_cache_restore_final_outputs,
    prepare_rule_cache_restore_staged_files,
    resume_run,
    retry_run,
    retry_run_rules,
)
from apps.api.models import (
    RunResumeRequest,
    RunRetryRequest,
    RunRuleCacheRestoreAdoptionApplyRequest,
    RunRuleCacheRestoreAdoptionPrepareRequest,
    RunRuleCacheRestoreFinalOutputApplyRequest,
    RunRuleCacheRestoreFinalOutputPrepareRequest,
    RunRuleCacheRestoreStagedFileApplyRequest,
    RunRuleCacheRestoreStagedFilePrepareRequest,
    RunRuleOutputInvalidationApplyRequest,
    RunRuleRetryRequest,
)
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


def test_rule_output_invalidation_apply_route_delegates_runtime_result(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    result = asyncio.run(
        apply_rule_output_invalidation(
            "run_rule_output_apply",
            RunRuleOutputInvalidationApplyRequest(
                confirmation="apply-rule-output-invalidation",
                planHash="c" * 64,
                actor="operator",
                reason="reviewed output scope",
            ),
        )
    )

    assert runtime.output_invalidation_calls == [
        (
            "run_rule_output_apply",
            {
                "confirmation": "apply-rule-output-invalidation",
                "planHash": "c" * 64,
                "actor": "operator",
                "reason": "reviewed output scope",
            },
        )
    ]
    assert result == {
        "data": {
            "schemaVersion": "rule-output-invalidation-apply-result.v1",
            "runId": "run_rule_output_apply",
            "status": "applied",
            "invalidatedOutputEdgeCount": 2,
            "invalidatedLineageEdgeCount": 2,
            "payloadDeleted": False,
        }
    }


def test_rule_staged_restore_routes_delegate_runtime_results(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    prepare_result = asyncio.run(
        prepare_rule_cache_restore_staged_files(
            "run_staged",
            RunRuleCacheRestoreStagedFilePrepareRequest(
                confirmation="prepare-rule-cache-restore-staged-files",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                actor="operator",
            ),
        )
    )
    apply_result = asyncio.run(
        apply_rule_cache_restore_staged_files(
            "run_staged",
            RunRuleCacheRestoreStagedFileApplyRequest(
                confirmation="apply-rule-cache-restore-staged-files",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                reason="reviewed",
            ),
        )
    )

    assert runtime.staged_prepare_calls == [
        (
            "run_staged",
            {
                "confirmation": "prepare-rule-cache-restore-staged-files",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "actor": "operator",
            },
        )
    ]
    assert runtime.staged_apply_calls == [
        (
            "run_staged",
            {
                "confirmation": "apply-rule-cache-restore-staged-files",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "reason": "reviewed",
            },
        )
    ]
    assert prepare_result["data"]["status"] == "ready"
    assert apply_result["data"]["status"] == "applied"


def test_rule_final_output_promotion_routes_delegate_runtime_results(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    prepare_result = asyncio.run(
        prepare_rule_cache_restore_final_outputs(
            "run_final_output",
            RunRuleCacheRestoreFinalOutputPrepareRequest(
                confirmation="prepare-rule-cache-restore-final-outputs",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                actor="operator",
            ),
        )
    )
    apply_result = asyncio.run(
        apply_rule_cache_restore_final_outputs(
            "run_final_output",
            RunRuleCacheRestoreFinalOutputApplyRequest(
                confirmation="apply-rule-cache-restore-final-outputs",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                reason="reviewed",
            ),
        )
    )

    assert runtime.final_output_prepare_calls == [
        (
            "run_final_output",
            {
                "confirmation": "prepare-rule-cache-restore-final-outputs",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "actor": "operator",
            },
        )
    ]
    assert runtime.final_output_apply_calls == [
        (
            "run_final_output",
            {
                "confirmation": "apply-rule-cache-restore-final-outputs",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "reason": "reviewed",
            },
        )
    ]
    assert prepare_result["data"]["status"] == "ready"
    assert apply_result["data"]["status"] == "applied"


def test_rule_cache_restore_adoption_routes_delegate_runtime_results(monkeypatch) -> None:
    runtime = FakeExecutionRuntime()
    monkeypatch.setattr("apps.api.execution_query_service.runtime_service", lambda: runtime)

    prepare_result = asyncio.run(
        prepare_rule_cache_restore_adoption(
            "run_restore_adoption",
            RunRuleCacheRestoreAdoptionPrepareRequest(
                confirmation="prepare-rule-cache-restore-adoption",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                actor="operator",
            ),
        )
    )
    apply_result = asyncio.run(
        apply_rule_cache_restore_adoption(
            "run_restore_adoption",
            RunRuleCacheRestoreAdoptionApplyRequest(
                confirmation="apply-rule-cache-restore-adoption",
                planHash="d" * 64,
                attemptId="att_1",
                leaseGeneration=1,
                reason="reviewed",
            ),
        )
    )

    assert runtime.adoption_prepare_calls == [
        (
            "run_restore_adoption",
            {
                "confirmation": "prepare-rule-cache-restore-adoption",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "actor": "operator",
            },
        )
    ]
    assert runtime.adoption_apply_calls == [
        (
            "run_restore_adoption",
            {
                "confirmation": "apply-rule-cache-restore-adoption",
                "planHash": "d" * 64,
                "attemptId": "att_1",
                "leaseGeneration": 1,
                "reason": "reviewed",
            },
        )
    ]
    assert prepare_result["data"]["status"] == "ready"
    assert apply_result["data"]["status"] == "applied"


class FakeExecutionRuntime:
    def __init__(self) -> None:
        self.rule_retry_calls = []
        self.output_invalidation_calls = []
        self.staged_prepare_calls = []
        self.staged_apply_calls = []
        self.final_output_prepare_calls = []
        self.final_output_apply_calls = []
        self.adoption_prepare_calls = []
        self.adoption_apply_calls = []
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

    def apply_rule_output_invalidation(self, run_id, payload):
        self.output_invalidation_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-output-invalidation-apply-result.v1",
                "runId": run_id,
                "status": "applied",
                "invalidatedOutputEdgeCount": 2,
                "invalidatedLineageEdgeCount": 2,
                "payloadDeleted": False,
            }
        }

    def prepare_rule_cache_restore_staged_files(self, run_id, payload):
        self.staged_prepare_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-staged-file-prepare-result.v1",
                "runId": run_id,
                "status": "ready",
            }
        }

    def apply_rule_cache_restore_staged_files(self, run_id, payload):
        self.staged_apply_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-staged-file-apply-result.v1",
                "runId": run_id,
                "status": "applied",
            }
        }

    def prepare_rule_cache_restore_final_outputs(self, run_id, payload):
        self.final_output_prepare_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-final-output-prepare-result.v1",
                "runId": run_id,
                "status": "ready",
            }
        }

    def apply_rule_cache_restore_final_outputs(self, run_id, payload):
        self.final_output_apply_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-final-output-apply-result.v1",
                "runId": run_id,
                "status": "applied",
            }
        }

    def prepare_rule_cache_restore_adoption(self, run_id, payload):
        self.adoption_prepare_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-adoption-prepare-result.v1",
                "runId": run_id,
                "status": "ready",
            }
        }

    def apply_rule_cache_restore_adoption(self, run_id, payload):
        self.adoption_apply_calls.append((run_id, payload))
        return {
            "data": {
                "schemaVersion": "rule-cache-restore-adoption-apply-result.v1",
                "runId": run_id,
                "status": "applied",
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
