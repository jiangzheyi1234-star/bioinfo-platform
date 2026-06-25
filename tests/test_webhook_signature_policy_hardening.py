from __future__ import annotations

import pytest

from apps.remote_runner.api_models import WorkflowTriggerCreateRequest
from apps.remote_runner.trigger_service import create_workflow_trigger_from_request
from tests.helpers.reference_database import make_configured_remote_runner


@pytest.mark.parametrize("provider", ["github", "slack", "stripe"])
def test_known_signed_webhook_trigger_creation_requires_signature_policy(
    provider: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SIGNATURE_POLICY_REQUIRED"):
        _create_trigger(
            cfg,
            provider=provider,
            trigger_spec={
                "provider": provider,
                "eventMatch": {"eventTypes": ["push"]},
            },
        )


@pytest.mark.parametrize("provider", ["github", "slack", "stripe"])
def test_known_signed_webhook_trigger_creation_requires_secret_ref(
    provider: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_configured_remote_runner(tmp_path)
    monkeypatch.setattr("apps.remote_runner.trigger_service.ensure_submission_ready", lambda _cfg: None)

    with pytest.raises(ValueError, match="WORKFLOW_TRIGGER_SIGNATURE_SECRET_REF_REQUIRED"):
        _create_trigger(
            cfg,
            provider=provider,
            trigger_spec={
                "provider": provider,
                "eventMatch": {"eventTypes": ["push"]},
                "signature": {"provider": provider},
            },
        )


def _create_trigger(
    cfg,
    *,
    provider: str,
    trigger_spec: dict[str, object],
) -> dict[str, object]:
    return create_workflow_trigger_from_request(
        cfg,
        WorkflowTriggerCreateRequest(
            name=f"{provider} webhook",
            sourceType="webhook",
            serverId="srv_primary",
            runSpec={
                "pipelineId": "file-summary-standard-v1",
                "inputs": [{"uploadId": "upl_reads", "filename": "reads.fastq"}],
            },
            triggerSpec=trigger_spec,
        ),
        actor="pytest",
    )["data"]
