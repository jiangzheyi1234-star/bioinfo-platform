from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

import apps.remote_runner.agent_run_authorization_authority as authority_module
import apps.remote_runner.agent_run_authorization_preview_service as preview_service
from apps.remote_runner.errors import WorkflowDesignRevisionConflictError
from apps.remote_runner.storage_core import get_connection
from core.contracts.agent_run_authorization_preview import (
    AgentRunAuthorizationPreview,
    agent_run_authorization_preview_hash,
)


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


def test_connection_reader_requires_and_preserves_caller_transaction(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]

    with get_connection(cfg) as connection:
        with pytest.raises(
            RuntimeError,
            match="AGENT_RUN_AUTHORIZATION_AUTHORITY_TRANSACTION_REQUIRED",
        ):
            authority_module.read_agent_run_authorization_authority_for_connection(
                connection,
                session_id,
            )

        connection.execute("BEGIN")
        snapshot = (
            authority_module.read_agent_run_authorization_authority_for_connection(
                connection,
                session_id,
            )
        )
        assert connection.in_transaction is True
        assert snapshot.session == candidate_case["session"]
        assert snapshot.plan == candidate_case["plan"]
        assert snapshot.workflow_revision == candidate_case["revision"]
        connection.rollback()

    comparison = snapshot.comparison_payload()
    comparison["session"]["stateVersion"] = -1
    assert snapshot.session["stateVersion"] == candidate_case["session"]["stateVersion"]
    wrapped = authority_module.read_agent_run_authorization_authority(
        cfg,
        session_id,
    )
    assert wrapped.comparison_payload() == snapshot.comparison_payload()


def test_prepare_checks_fresh_admission_before_candidate_build(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    snapshot = authority_module.read_agent_run_authorization_authority(
        cfg,
        session_id,
    )
    missing_budget = replace(snapshot, effect_budget=None)
    monkeypatch.setattr(
        authority_module,
        "read_agent_run_authorization_authority",
        lambda *_args, **_kwargs: missing_budget,
    )
    monkeypatch.setattr(
        authority_module,
        "build_agent_fastq_qc_execution_candidate",
        lambda *_args, **_kwargs: pytest.fail("candidate must not be built"),
    )

    with pytest.raises(
        WorkflowDesignRevisionConflictError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_EFFECT_BUDGET_REQUIRED",
    ):
        authority_module.prepare_agent_run_authorization_authority(
            cfg,
            session_id,
            actor="user-1",
        )


def test_prepare_rejects_authority_drift_after_candidate_build(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    first = authority_module.read_agent_run_authorization_authority(cfg, session_id)
    drifted_session = dict(first.session)
    drifted_session["stateVersion"] += 1
    snapshots = iter((first, replace(first, session=drifted_session)))
    candidate_built = False
    original_candidate_builder = (
        authority_module.build_agent_fastq_qc_execution_candidate
    )

    def counted_candidate_builder(*args: Any, **kwargs: Any) -> Any:
        nonlocal candidate_built
        candidate_built = True
        return original_candidate_builder(*args, **kwargs)

    monkeypatch.setattr(
        authority_module,
        "read_agent_run_authorization_authority",
        lambda *_args, **_kwargs: next(snapshots),
    )
    monkeypatch.setattr(
        authority_module,
        "build_agent_fastq_qc_execution_candidate",
        counted_candidate_builder,
    )

    with pytest.raises(
        WorkflowDesignRevisionConflictError,
        match="AGENT_RUN_AUTHORIZATION_PREVIEW_AUTHORITY_CHANGED",
    ):
        authority_module.prepare_agent_run_authorization_authority(
            cfg,
            session_id,
            actor="user-1",
        )
    assert candidate_built is True


def test_candidate_build_runs_after_read_transaction_is_released(
    candidate_case: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]
    original_candidate_builder = (
        authority_module.build_agent_fastq_qc_execution_candidate
    )
    writer_acquired = False

    def candidate_with_writer_probe(*args: Any, **kwargs: Any) -> Any:
        nonlocal writer_acquired
        with get_connection(cfg) as writer:
            writer.execute("PRAGMA busy_timeout = 0")
            writer.execute("BEGIN IMMEDIATE")
            writer_acquired = True
            writer.rollback()
        return original_candidate_builder(*args, **kwargs)

    monkeypatch.setattr(
        authority_module,
        "build_agent_fastq_qc_execution_candidate",
        candidate_with_writer_probe,
    )

    prepared = authority_module.prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor="user-1",
    )

    assert writer_acquired is True
    assert prepared.snapshot.session["sessionId"] == session_id


def test_prepared_preview_is_deterministic_and_matches_existing_projection(
    candidate_case: dict[str, Any],
) -> None:
    cfg = candidate_case["cfg"]
    session_id = candidate_case["session"]["sessionId"]

    first = authority_module.prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor="user-1",
    )
    second = authority_module.prepare_agent_run_authorization_authority(
        cfg,
        session_id,
        actor="user-1",
    )
    existing = preview_service.build_agent_run_authorization_preview(
        cfg,
        session_id,
        actor="user-1",
    )

    assert first.preview == second.preview == existing
    assert (
        AgentRunAuthorizationPreview.model_validate(first.preview).runtime_payload()
        == first.preview
    )
    assert (
        agent_run_authorization_preview_hash(first.preview)
        == first.preview["previewHash"]
    )
    assert (
        first.preview
        == authority_module.build_agent_run_authorization_preview_payload(
            first.snapshot,
            first.candidate,
        )
    )
