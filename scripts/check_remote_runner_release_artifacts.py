from __future__ import annotations

import json
import hashlib
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
from core.remote_runner.release_manifest import (  # noqa: E402
    REMOTE_RUNNER_ARTIFACT,
    WORKFLOW_RUNTIME_ARTIFACT,
)


def _print_json(label: str, payload: object) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def main() -> int:
    try:
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
    except RemoteRunnerArtifactError as exc:
        _print_json(
            "RELEASE_ARTIFACTS",
            {
                "ok": False,
                "message": str(exc),
                "remoteRunner": asdict(REMOTE_RUNNER_ARTIFACT),
                "workflowRuntime": asdict(WORKFLOW_RUNTIME_ARTIFACT),
            },
        )
        return 1

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
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
