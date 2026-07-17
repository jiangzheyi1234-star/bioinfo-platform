#!/usr/bin/env python3
"""Validate a staging artifact while protocol activation remains fail-closed.

Protocol v5 requires config, systemd unit, release, lifetime fence, owner
evidence, and readiness proof to change under one remote activation transaction.
The former release-only staging swap could not prove that boundary, so this
entry point intentionally performs no SSH connection or remote mutation until
the activation transaction is implemented.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any, NoReturn


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.contracts.runner_protocol_runtime import (  # noqa: E402
    require_current_runner_protocol_expectation,
)
from core.remote_runner.artifact_io import (  # noqa: E402
    read_expected_sha256,
    read_manifest,
    sha256_file,
)
from core.remote_runner.protocol_manifest import (  # noqa: E402
    require_current_runner_protocol_manifest,
)


STAGING_PROTOCOL_ACTIVATION_REQUIRED = (
    "STAGING_PROTOCOL_ACTIVATION_REQUIRED: remote mutation is disabled until "
    "config, systemd unit, release, rollback, and exact readiness share one "
    "activation transaction"
)
_ARTIFACT_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DEPLOY_NONCE_PATTERN = re.compile(r"[0-9a-f]{12}\Z")


def _require_artifact_version(
    value: object,
    *,
    make_error: type[Exception],
) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _ARTIFACT_VERSION_PATTERN.fullmatch(value) is None
    ):
        raise make_error("artifact version is invalid")
    return value


def _print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _archive_text(artifact: Path, member_name: str) -> str:
    with tarfile.open(artifact, "r:gz") as archive:
        member = next(
            (
                item
                for item in archive.getmembers()
                if item.name.strip("./") == member_name
            ),
            None,
        )
        if member is None:
            raise RuntimeError(f"artifact member missing: {member_name}")
        handle = archive.extractfile(member)
        if handle is None:
            raise RuntimeError(f"artifact member unreadable: {member_name}")
        return handle.read().decode("utf-8")


def _archive_member_names(artifact: Path) -> set[str]:
    with tarfile.open(artifact, "r:gz") as archive:
        return {item.name.strip("./") for item in archive.getmembers()}


def validate_staging_artifact(artifact: Path) -> dict[str, Any]:
    checksum_path = Path(str(artifact) + ".sha256")
    if not artifact.is_file():
        raise RuntimeError(f"artifact not found: {artifact}")
    if not checksum_path.is_file():
        raise RuntimeError(f"artifact checksum not found: {checksum_path}")
    expected = read_expected_sha256(checksum_path)
    actual = sha256_file(artifact)
    if actual != expected:
        raise RuntimeError(
            f"artifact checksum mismatch: expected={expected} actual={actual}"
        )
    manifest = read_manifest(artifact)
    if manifest.get("service") != "h2ometa-remote":
        raise RuntimeError(
            f"unexpected artifact service: {manifest.get('service')}"
        )
    version = _require_artifact_version(
        manifest.get("version"),
        make_error=RuntimeError,
    )
    runner_protocol = require_current_runner_protocol_manifest(
        manifest,
        make_error=RuntimeError,
    )

    executor_artifacts = _archive_text(
        artifact,
        "remote_runner/executor_artifacts.py",
    )
    reconciler = _archive_text(artifact, "remote_runner/reconciler.py")
    actions = _archive_text(artifact, "remote_runner/reconciler_actions.py")
    process_owner = _archive_text(artifact, "remote_runner/process_owner.py")
    owner_contract = _archive_text(
        artifact,
        "core/contracts/runner_process_owner.py",
    )
    service_unit = _archive_text(artifact, "h2ometa-remote.service")
    archive_members = _archive_member_names(artifact)
    markers = {
        "candidateAdoption": "adopt_verified_candidate_outputs"
        in executor_artifacts,
        "activeReconciler": "run_active_reconciler_once" in reconciler,
        "sigkillEscalation": "signal.SIGKILL" in actions,
        "runWorkerResourceConfig": (
            "remote_runner/worker_resource_config.py" in archive_members
        ),
        "multiSlotGate": "H2OMETA_REMOTE_ENABLE_MULTI_SLOT"
        in _archive_text(artifact, "remote_runner/worker_supervisor.py"),
        "cancelResultMapping": "RUN_CANCELLED"
        in _archive_text(artifact, "remote_runner/executor_outcomes.py"),
        "executionObservability": (
            "remote_runner/execution_observability.py" in archive_members
            and "execution-observability.v1"
            in _archive_text(artifact, "remote_runner/execution_observability.py")
        ),
        "executionPolicy": (
            "remote_runner/execution_policy.py" in archive_members
            and "attempt_start_to_close_exceeded"
            in _archive_text(artifact, "remote_runner/execution_policy.py")
            and "expire_queued_jobs_over_ttl" in actions
        ),
        "processOwnerEvidence": (
            "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in process_owner
            and "h2ometa.runner-process-owner.v1" in owner_contract
        ),
        "processOwnerRestartPrevention": (
            "RestartPreventExitStatus=73 74 75" in service_unit
        ),
    }
    missing = [key for key, present in markers.items() if not present]
    if missing:
        raise RuntimeError(
            f"artifact is missing P0-1 markers: {', '.join(missing)}"
        )
    return {
        "path": str(artifact),
        "sha256": actual,
        "version": version,
        "platform": str(manifest.get("platform") or ""),
        "runnerProtocolVersion": runner_protocol["protocolVersion"],
        "runnerProtocolFingerprint": manifest["runnerProtocolFingerprint"],
        **markers,
    }


def _remote_deploy_script(
    *,
    remote_artifact: str,
    artifact_sha256: str,
    runner_protocol_version: str,
    runner_protocol_fingerprint: str,
    version: str,
    nonce: str,
) -> NoReturn:
    """Validate every caller-controlled value, then refuse remote mutation."""

    if not isinstance(remote_artifact, str) or not remote_artifact:
        raise ValueError("staging remote artifact path is invalid")
    _require_artifact_version(version, make_error=ValueError)
    if not isinstance(nonce, str) or _DEPLOY_NONCE_PATTERN.fullmatch(nonce) is None:
        raise ValueError("staging deploy nonce is invalid")
    if not isinstance(artifact_sha256, str) or len(artifact_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in artifact_sha256
    ):
        raise ValueError("staging artifact sha256 is invalid")
    require_current_runner_protocol_expectation(
        runner_protocol_version,
        runner_protocol_fingerprint,
        make_error=ValueError,
    )
    raise RuntimeError(STAGING_PROTOCOL_ACTIVATION_REQUIRED)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a development remote-runner artifact. Remote mutation is "
            "fail-closed until the protocol activation transaction is available."
        )
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--allow-staging-deploy",
        action="store_true",
        help=(
            "Acknowledge a future staging mutation. The current command still "
            "fails closed after local validation."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.allow_staging_deploy:
        print("ERROR: --allow-staging-deploy is required.")
        return 2
    artifact = args.artifact.resolve()
    metadata = validate_staging_artifact(artifact)
    _print_json("STAGING_ARTIFACT", metadata)
    try:
        _remote_deploy_script(
            remote_artifact="<remote-mutation-disabled>",
            artifact_sha256=str(metadata["sha256"]),
            runner_protocol_version=str(metadata["runnerProtocolVersion"]),
            runner_protocol_fingerprint=str(
                metadata["runnerProtocolFingerprint"]
            ),
            version=str(metadata["version"]),
            nonce="000000000000",
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 3
    raise AssertionError("staging mutation unexpectedly became reachable")


if __name__ == "__main__":
    raise SystemExit(main())
