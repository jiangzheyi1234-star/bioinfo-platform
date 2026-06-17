from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Criterion:
    key: str
    weight: int
    files: tuple[str, ...]
    needles: tuple[str, ...]
    recommendation: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        key="release_traceability",
        weight=12,
        files=("config/remote-runner-release-manifest.json", "docs/release-policy.md"),
        needles=("sha256", "size_bytes", "source_commits", "h2ometa-runtime-vX.Y.Z"),
        recommendation="Keep runtime artifacts locked to Release assets, SHA-256, size, source commit, and tag policy.",
    ),
    Criterion(
        key="immutable_remote_layout",
        weight=9,
        files=("core/remote_runner/layout.py", "docs/remote-agent-deployment-strategy.md"),
        needles=("releases", "current", "shared", "tools", "locks"),
        recommendation="Keep immutable releases separate from shared mutable uploads/results/work/logs.",
    ),
    Criterion(
        key="idempotent_ssh_bootstrap",
        weight=10,
        files=("core/remote_runner/manager.py", "core/remote_runner/reuse.py", "core/remote_runner/install_lock.py"),
        needles=("_try_reuse_existing_runner", "_acquire_remote_install_lock", "artifact_sha"),
        recommendation="Bootstrap should reuse matching installs and serialize installs with a remote lock.",
    ),
    Criterion(
        key="managed_service_supervision",
        weight=10,
        files=("core/remote_runner/bootstrap_activation.py", "scripts/inspect_remote_runner_service.py"),
        needles=("systemctl --user", "h2ometa-remote.service", "status"),
        recommendation="Prefer systemd user service, with script/background fallback only for unsupported hosts.",
    ),
    Criterion(
        key="readiness_gate",
        weight=11,
        files=("core/remote_runner/readiness.py", "core/app_runtime/server_state.py", "core/app_runtime/server_health.py"),
        needles=("_wait_for_runner_health", "workflowRuntime", "pipelineRegistry", "ready"),
        recommendation="Gate run submission and UI readiness on layered runner/workflow/pipeline health.",
    ),
    Criterion(
        key="bootstrap_canary",
        weight=10,
        files=("core/remote_runner/bootstrap_activation.py", "scripts/remote_smoke.py"),
        needles=("_run_bootstrap_canary", "file-summary-v1", "artifactCount"),
        recommendation="Keep a real post-start canary that uploads input, submits a run, and verifies artifacts.",
    ),
    Criterion(
        key="rollback_activation",
        weight=10,
        files=("core/remote_runner/bootstrap_activation.py", "core/remote_runner/manager.py"),
        needles=("_attempt_release_rollback", "previous_release", "rolled_back"),
        recommendation="Activation failures after release switch should restore previous config and current symlink.",
    ),
    Criterion(
        key="operator_diagnostics",
        weight=8,
        files=("scripts/inspect_remote_runner_service.py", "docs/managed-workflow-runtime-runbook.md"),
        needles=("journalctl --user", "runner-state.json", "Diagnostics"),
        recommendation="Keep read-only diagnostics for service status, logs, current release, config, and runtime state.",
    ),
    Criterion(
        key="remote_acceptance_tests",
        weight=10,
        files=("scripts/remote_smoke.py", "scripts/remote_pipeline_smoke.py", "tests/test_remote_runner_bootstrap_deploy.py"),
        needles=("--bootstrap", "remote_smoke", "test_bootstrap"),
        recommendation="Maintain smoke and unit coverage for bootstrap, remote readiness, and pipeline execution.",
    ),
    Criterion(
        key="documented_lifecycle_states",
        weight=10,
        files=("docs/remote-agent-deployment-strategy.md",),
        needles=("resolving_artifacts", "running_canary", "rollback_succeeded", "rollback_failed"),
        recommendation="Expose a shared lifecycle vocabulary for UI, API, logs, and support scripts.",
    ),
)


def read_file(path: str) -> str:
    full_path = REPO_ROOT / path
    if not full_path.exists():
        return ""
    return full_path.read_text(encoding="utf-8", errors="replace")


def score_criterion(criterion: Criterion) -> dict[str, object]:
    evidence = "\n".join(read_file(path) for path in criterion.files)
    missing_files = [path for path in criterion.files if not (REPO_ROOT / path).exists()]
    missing_needles = [needle for needle in criterion.needles if needle not in evidence]
    passed = not missing_files and not missing_needles
    return {
        "key": criterion.key,
        "weight": criterion.weight,
        "score": criterion.weight if passed else 0,
        "passed": passed,
        "missingFiles": missing_files,
        "missingEvidence": missing_needles,
        "recommendation": criterion.recommendation,
    }


def build_scorecard() -> dict[str, object]:
    criteria = [score_criterion(criterion) for criterion in CRITERIA]
    total = sum(int(item["score"]) for item in criteria)
    max_score = sum(criterion.weight for criterion in CRITERIA)
    return {
        "schemaVersion": "h2ometa-remote-agent-scorecard.v1",
        "score": total,
        "maxScore": max_score,
        "percent": round(total * 100 / max_score, 1),
        "criteria": criteria,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the H2OMeta remote agent lifecycle against the deployment strategy.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--validation-plan", action="store_true", help="Print the recommended real validation sequence.")
    args = parser.parse_args()

    scorecard = build_scorecard()
    if args.json:
        print(json.dumps(scorecard, indent=2, sort_keys=True))
        return 0

    if args.validation_plan:
        print("Recommended validation sequence:")
        print("1. Windows preflight: uv run python scripts\\check_release_manifest_traceability.py --release-tag h2ometa-runtime-vX.Y.Z")
        print("2. Windows artifact gate: uv run python scripts\\check_remote_runner_release_artifacts.py --require-supply-chain")
        print("3. Windows launcher: run.bat --web")
        print("4. Windows remote control-plane smoke: uv run python scripts\\remote_smoke.py --bootstrap")
        print("5. Windows end-to-end pipeline smoke: uv run python scripts\\remote_pipeline_smoke.py")
        print("6. Read-only remote diagnostics on failure: uv run python scripts\\inspect_remote_runner_service.py")
        print("7. WSL-owned quality gates, run manually from WSL Codex CLI: uv run pytest tests/test_remote_runner_bootstrap_deploy.py tests/test_remote_runner_reuse_lock_manager.py tests/test_release_manifest_traceability.py")
        return 0

    print(f"Remote agent lifecycle score: {scorecard['score']}/{scorecard['maxScore']} ({scorecard['percent']}%)")
    for item in scorecard["criteria"]:
        status = "PASS" if item["passed"] else "MISS"
        print(f"{status} {item['key']} ({item['score']}/{item['weight']})")
        if not item["passed"]:
            missing_files = item["missingFiles"]
            missing_evidence = item["missingEvidence"]
            if missing_files:
                print(f"  missing files: {', '.join(missing_files)}")
            if missing_evidence:
                print(f"  missing evidence: {', '.join(missing_evidence)}")
            print(f"  next: {item['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


