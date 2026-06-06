from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_durable_control_plane_roadmap_adr_records_phase_zero_guardrails() -> None:
    adr = ROOT / "docs/adr/2026-06-07-durable-control-plane-roadmap.md"

    assert adr.exists()
    source = adr.read_text(encoding="utf-8")

    assert "docs/adr/2026-06-06-draft-asset-run-boundary.md" in source
    assert "Draft -> WorkflowRevision -> RunLedger" in source
    assert "remote runner is the source of truth" in source
    assert "run_attempts" in source
    assert "run_leases" in source
    assert "workflow_revisions" in source
    assert "run_commands" in source
    assert "payload_hash" in source
    assert "event_hash" in source
    assert "prev_event_hash" in source
    assert "projection/cache" in source
    assert "old ad hoc executable run payloads must fail loudly" in source
    assert "Kubernetes" in source
    assert "Temporal" in source
    assert "mandatory Redis" in source
    assert "AssetRevision" not in source
