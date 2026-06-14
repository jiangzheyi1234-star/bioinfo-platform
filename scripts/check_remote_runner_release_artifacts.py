from __future__ import annotations

import argparse
import json
import hashlib
import os
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.artifact import (  # noqa: E402
    RemoteRunnerArtifactError,
    RemoteRunnerArtifactProvider,
    WorkflowRuntimeArtifactProvider,
)
from core.remote_runner.artifact_io import read_expected_sha256, read_manifest  # noqa: E402
from core.remote_runner.artifact_models import RemoteRunnerArtifact  # noqa: E402
from core.remote_runner.artifact_diagnostics import supply_chain_metadata  # noqa: E402
from core.remote_runner.release_manifest import (  # noqa: E402
    REMOTE_RUNNER_ARTIFACT,
    WORKFLOW_RUNTIME_ARTIFACT,
)
from core.remote_runner.remote_runner_artifact_validation import (  # noqa: E402
    verify_bundled_runtime_entrypoints,
    verify_required_wrapper_assets,
)


def _print_json(label: str, payload: object) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cmd_set_line(name: str, value: Path) -> str:
    return f'set "{name}={value}"'


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify manifest-declared remote runner release artifacts.",
    )
    parser.add_argument(
        "--cmd-env",
        action="store_true",
        help="Emit Windows cmd.exe set commands for launcher consumption.",
    )
    parser.add_argument(
        "--require-supply-chain",
        action="store_true",
        help=(
            "Require release manifest SBOM plus provenance or attestation metadata. "
            "Use this for production release validation, not routine local launcher startup."
        ),
    )
    parser.add_argument(
        "--allow-staging-runner-bundle",
        action="store_true",
        help=(
            "Allow H2OMETA_REMOTE_RUNNER_BUNDLE to point at a local staging artifact whose sidecar "
            "checksum is valid but whose sha256 has not been promoted into the release manifest."
        ),
    )
    return parser.parse_args(argv)


def _verify_lock(spec, *, platform: str) -> dict[str, object]:
    relative = spec.conda_explicit_specs.get(platform)
    if not relative:
        raise RemoteRunnerArtifactError(f"{spec.key} missing explicit conda spec for {platform}")
    path = REPO_ROOT / relative
    if not path.exists():
        raise RemoteRunnerArtifactError(f"{spec.key} explicit conda spec not found: {path}")
    first_line = path.read_text(encoding="utf-8").splitlines()[0:1]
    if first_line != ["@EXPLICIT"]:
        raise RemoteRunnerArtifactError(f"{spec.key} explicit conda spec must start with @EXPLICIT: {path}")
    digest = _sha256_file(path)
    declared = str(spec.lock_sha256.get(platform) or "").strip().lower()
    if declared and declared != digest:
        raise RemoteRunnerArtifactError(f"{spec.key} explicit conda spec sha256 mismatch: {path}")
    return {"path": str(path), "sha256": digest}


def _verify_supply_chain(spec, *, platform: str) -> dict[str, object]:
    metadata = supply_chain_metadata(spec, platform=platform)
    if not metadata["complete"]:
        gaps = [str(item) for item in metadata["missingRequired"]]
        gaps.extend(f"pending:{item}" for item in metadata.get("pendingFields", []))
        gaps.extend(f"invalid:{item}" for item in metadata.get("invalidFields", []))
        message = ", ".join(gaps) if gaps else "unknown"
        raise RemoteRunnerArtifactError(f"{spec.key} release supply-chain metadata incomplete for {platform}: {message}")
    return metadata


def _resolve_staging_runner_bundle() -> RemoteRunnerArtifact:
    raw = str(os.environ.get("H2OMETA_REMOTE_RUNNER_BUNDLE", "") or "").strip()
    if not raw:
        raise RemoteRunnerArtifactError("--allow-staging-runner-bundle requires H2OMETA_REMOTE_RUNNER_BUNDLE")
    archive_path = Path(raw).resolve()
    checksum_path = Path(str(archive_path) + ".sha256")
    if not archive_path.is_file():
        raise RemoteRunnerArtifactError(f"staging remote runner artifact not found: {archive_path}")
    if not checksum_path.is_file():
        raise RemoteRunnerArtifactError(f"staging remote runner checksum not found: {checksum_path}")
    expected = read_expected_sha256(checksum_path)
    actual = _sha256_file(archive_path)
    if actual != expected:
        raise RemoteRunnerArtifactError(f"staging remote runner artifact sha256 mismatch: {archive_path}")
    manifest = read_manifest(archive_path)
    platform = str(manifest.get("platform") or "")
    if str(manifest.get("service") or "") != REMOTE_RUNNER_ARTIFACT.service:
        raise RemoteRunnerArtifactError(f"staging remote runner artifact manifest has unexpected service: {archive_path}")
    if str(manifest.get("version") or "") != REMOTE_RUNNER_ARTIFACT.version:
        raise RemoteRunnerArtifactError(f"staging remote runner artifact manifest version mismatch: {archive_path}")
    if platform != REMOTE_RUNNER_ARTIFACT.default_platform:
        raise RemoteRunnerArtifactError(f"staging remote runner artifact platform mismatch: {archive_path}")
    verify_bundled_runtime_entrypoints(archive_path)
    verify_required_wrapper_assets(archive_path)
    return RemoteRunnerArtifact(
        version=REMOTE_RUNNER_ARTIFACT.version,
        platform=platform,
        archive_path=archive_path,
        sha256=actual,
        manifest=manifest,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.require_supply_chain:
            _verify_supply_chain(REMOTE_RUNNER_ARTIFACT, platform=REMOTE_RUNNER_ARTIFACT.default_platform)
            _verify_supply_chain(WORKFLOW_RUNTIME_ARTIFACT, platform=WORKFLOW_RUNTIME_ARTIFACT.default_platform)
        if args.allow_staging_runner_bundle:
            runner = _resolve_staging_runner_bundle()
        else:
            runner = RemoteRunnerArtifactProvider(repo_root=REPO_ROOT).resolve(
                version=REMOTE_RUNNER_ARTIFACT.version,
                platform=REMOTE_RUNNER_ARTIFACT.default_platform,
            )
        workflow = WorkflowRuntimeArtifactProvider(repo_root=REPO_ROOT).resolve(
            version=WORKFLOW_RUNTIME_ARTIFACT.version,
            platform=WORKFLOW_RUNTIME_ARTIFACT.default_platform,
        )
        runner_lock = _verify_lock(REMOTE_RUNNER_ARTIFACT, platform=runner.platform)
        workflow_lock = _verify_lock(WORKFLOW_RUNTIME_ARTIFACT, platform=workflow.platform)
        runner_supply_chain = supply_chain_metadata(REMOTE_RUNNER_ARTIFACT, platform=runner.platform)
        workflow_supply_chain = supply_chain_metadata(WORKFLOW_RUNTIME_ARTIFACT, platform=workflow.platform)
    except RemoteRunnerArtifactError as exc:
        payload = {
            "ok": False,
            "message": str(exc),
            "remoteRunner": asdict(REMOTE_RUNNER_ARTIFACT),
            "workflowRuntime": asdict(WORKFLOW_RUNTIME_ARTIFACT),
        }
        if args.cmd_env:
            print(f"RELEASE_ARTIFACTS: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", file=sys.stderr)
        else:
            _print_json("RELEASE_ARTIFACTS", payload)
        return 1

    if args.cmd_env:
        print(_cmd_set_line("H2OMETA_REMOTE_RUNNER_BUNDLE", runner.archive_path))
        print(_cmd_set_line("H2OMETA_WORKFLOW_RUNTIME_BUNDLE", workflow.archive_path))
    else:
        _print_json(
            "RELEASE_ARTIFACTS",
            {
                "ok": True,
                "remoteRunner": {
                    "path": str(runner.archive_path),
                    "version": runner.version,
                    "platform": runner.platform,
                    "sha256": runner.sha256,
                    "lock": runner_lock,
                    "supplyChain": runner_supply_chain,
                },
                "workflowRuntime": {
                    "path": str(workflow.archive_path),
                    "version": workflow.version,
                    "platform": workflow.platform,
                    "sha256": workflow.sha256,
                    "snakemakeVersion": str((workflow.manifest.get("packages") or {}).get("snakemake") or ""),
                    "snakemake": workflow.snakemake_entrypoint,
                    "conda": workflow.conda_entrypoint,
                    "condaUnpack": workflow.conda_unpack_entrypoint,
                    "lock": workflow_lock,
                    "supplyChain": workflow_supply_chain,
                },
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
