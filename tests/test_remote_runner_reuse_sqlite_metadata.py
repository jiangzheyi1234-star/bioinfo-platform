from __future__ import annotations

from core.remote_runner.metadata import build_fast_reuse_metadata
from tests.helpers.remote_runner_control_plane import (
    packaged_remote_runner_sqlite_evidence,
)


def test_fast_reuse_metadata_rebinds_sqlite_evidence_to_resolved_artifact() -> None:
    current = packaged_remote_runner_sqlite_evidence()
    stale = {**current, "version": "3.99.0", "build": "forged"}

    metadata = build_fast_reuse_metadata(
        server_record={
            "bootstrap_metadata": {"tooling": {"service_runtime": {"sqlite": stale}}}
        },
        version="0.1.6",
        remote_service_python="/runner/current/runtime/bin/python",
        sqlite_evidence=current,
    )

    assert metadata["tooling"]["service_runtime"]["sqlite"] == current
    assert metadata["tooling"]["service_runtime"]["sqlite"] is not current
