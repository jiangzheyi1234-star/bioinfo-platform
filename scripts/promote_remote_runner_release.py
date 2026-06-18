#!/usr/bin/env python3
"""Promote a remote-runner runtime release only after proof checks pass."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_remote_runner_release_readiness as readiness  # noqa: E402
from scripts import update_remote_runner_release_manifest as updater  # noqa: E402


DEFAULT_MANIFEST = REPO_ROOT / "config" / "remote-runner-release-manifest.json"
RELEASE_TAG_RE = re.compile(r"^h2ometa-runtime-v[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$")
GITHUB_RELEASE_ASSET_RE = re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+/releases/assets/\d+$")
REQUIRED_ARTIFACT_KEYS = {"remote_runner", "workflow_runtime"}
PRODUCTION_REQUIRED_FIELDS = (
    "sha256",
    "size_bytes",
    "lock_sha256",
    "download_urls",
    "sbom_urls",
    "provenance_urls",
    "attestation_urls",
    "signature_urls",
    "builder_ids",
    "source_refs",
    "source_commits",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--metadata", required=True, help="Path to release-artifacts-metadata.json.")
    parser.add_argument("--manifest-metadata", required=True, help="Path to release-manifest-metadata.json.")
    parser.add_argument("--attestations", required=True, help="Path to release-attestations.json.")
    parser.add_argument(
        "--github-attestations",
        default="",
        help="Optional path to release-github-attestations.json emitted by hosted GitHub attestation steps.",
    )
    parser.add_argument(
        "--require-github-attestations",
        action="store_true",
        help="Require --github-attestations to contain hosted GitHub/Sigstore attestation URLs.",
    )
    parser.add_argument("--published-assets", required=True, help="Path to release-published-assets.json.")
    parser.add_argument("--release-gate-evidence", required=True, help="Path to release-gate-evidence.json.")
    parser.add_argument("--release-tag", required=True, help="Runtime release tag, for example h2ometa-runtime-v0.1.2.")
    parser.add_argument(
        "--output-manifest",
        default="",
        help="Write the candidate manifest here. Defaults to dist/remote-runner/promoted-release-manifest.json.",
    )
    parser.add_argument(
        "--summary-json",
        default=str(Path("dist") / "remote-runner" / "release-promotion-summary.json"),
        help="Write the machine-readable promotion summary here.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the promoted manifest to --manifest after all production checks pass.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary_path = Path(args.summary_json)
    results: list[dict[str, Any]] = []
    try:
        summary = promote_release(args, results)
    except Exception as exc:
        results.append({"name": "release-promotion", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        summary = build_summary(ok=False, args=args, checks=results)
    write_json(summary_path, summary)
    print("RELEASE_PROMOTION_SUMMARY: " + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["ok"] else 1


def promote_release(args: argparse.Namespace, results: list[dict[str, Any]]) -> dict[str, Any]:
    metadata_path = Path(args.metadata)
    manifest_metadata_path = Path(args.manifest_metadata)
    attestations_path = Path(args.attestations)
    github_attestations_path = Path(args.github_attestations) if args.github_attestations else None
    published_assets_path = Path(args.published_assets)
    release_gate_path = Path(args.release_gate_evidence)
    manifest_path = Path(args.manifest)
    output_manifest_path = Path(args.output_manifest) if args.output_manifest else Path("dist") / "remote-runner" / "promoted-release-manifest.json"

    metadata = load_json(metadata_path)
    manifest_metadata = load_json(manifest_metadata_path)
    attestations = load_json(attestations_path)
    github_attestations = load_json(github_attestations_path) if github_attestations_path is not None else None
    published_assets = load_json(published_assets_path)
    gate_evidence = load_json(release_gate_path)
    current_manifest = load_json(manifest_path)

    source_commit = require_release_identity(
        metadata=metadata,
        manifest_metadata=manifest_metadata,
        gate_evidence=gate_evidence,
        published_assets=published_assets,
        release_tag=str(args.release_tag),
    )
    results.append({"name": "release-identity", "ok": True, "sourceCommit": source_commit, "releaseTag": args.release_tag})

    readiness.validate_ci_build_outputs(
        metadata_path=metadata_path,
        manifest_metadata_path=manifest_metadata_path,
        attestations_path=attestations_path,
    )
    results.append({"name": "ci-build-metadata", "ok": True})

    if args.require_github_attestations and github_attestations_path is None:
        raise ValueError("--require-github-attestations requires --github-attestations")
    if github_attestations_path is not None:
        readiness.validate_github_attestations(
            github_attestations_path,
            metadata_path=metadata_path,
            require_hosted=bool(args.require_github_attestations),
        )
        mode = str((github_attestations or {}).get("mode") or "").strip()
        check_name = (
            "github-hosted-attestations"
            if updater.hosted_attestations_enabled(github_attestations)
            else "github-attestations-summary"
        )
        results.append({"name": check_name, "ok": True, "mode": mode})

    readiness.validate_release_gate_evidence(release_gate_path)
    results.append({"name": "release-gate-evidence", "ok": True})

    download_urls, sbom_urls = updater.merge_published_asset_urls(
        metadata=metadata,
        published_assets=published_assets,
        download_urls={},
        sbom_urls={},
    )
    candidate_manifest = updater.update_manifest(
        current_manifest,
        metadata=metadata,
        attestations=attestations,
        download_urls=download_urls,
        sbom_urls=sbom_urls,
        published_assets=published_assets,
        github_attestations=github_attestations,
    )
    validate_production_manifest(candidate_manifest, source_commit=source_commit, release_tag=str(args.release_tag))
    results.append({"name": "production-manifest", "ok": True})

    write_json(output_manifest_path, candidate_manifest)
    if args.apply:
        write_json(manifest_path, candidate_manifest)
    return build_summary(
        ok=True,
        args=args,
        checks=results,
        candidate_manifest=output_manifest_path,
        applied_manifest=manifest_path if args.apply else None,
        source_commit=source_commit,
    )


def require_release_identity(
    *,
    metadata: dict[str, Any],
    manifest_metadata: dict[str, Any],
    gate_evidence: dict[str, Any],
    published_assets: dict[str, Any],
    release_tag: str,
) -> str:
    if not RELEASE_TAG_RE.fullmatch(release_tag):
        raise ValueError(f"release tag must match h2ometa-runtime-vX.Y.Z: {release_tag}")
    source_commit = require_commit(metadata.get("sourceCommit"), "metadata.sourceCommit")
    if require_commit(metadata.get("sourceRef"), "metadata.sourceRef") != source_commit:
        raise ValueError("metadata.sourceRef must equal metadata.sourceCommit for promotion")
    if require_commit(manifest_metadata.get("sourceCommit"), "manifestMetadata.sourceCommit") != source_commit:
        raise ValueError("manifest metadata sourceCommit mismatch")
    if require_commit(gate_evidence.get("sourceCommit"), "releaseGate.sourceCommit") != source_commit:
        raise ValueError("release gate sourceCommit mismatch")
    runner_sha = require_sha256(
        require_artifact(metadata, "remote_runner").get("sha256"),
        "metadata.remote_runner.sha256",
    )
    gate_bundle = gate_evidence.get("remoteRunnerBundle")
    if not isinstance(gate_bundle, dict):
        raise ValueError("release gate remoteRunnerBundle must be an object")
    gate_runner_sha = require_sha256(gate_bundle.get("sha256"), "releaseGate.remoteRunnerBundle.sha256")
    if gate_runner_sha != runner_sha:
        raise ValueError("release gate remoteRunnerBundle sha256 mismatch")
    if str(published_assets.get("releaseTag") or "").strip() != release_tag:
        raise ValueError("published assets releaseTag mismatch")
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("metadata.artifacts must be a list")
    keys = {str(item.get("artifactKey") or "") for item in artifacts if isinstance(item, dict)}
    if keys != REQUIRED_ARTIFACT_KEYS:
        raise ValueError("promotion metadata must include remote_runner and workflow_runtime")
    tag_commit = git_commit(release_tag)
    if tag_commit != source_commit:
        raise ValueError(f"release tag {release_tag} points at {tag_commit}, not {source_commit}")
    return source_commit


def require_artifact(metadata: dict[str, Any], artifact_key: str) -> dict[str, Any]:
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("metadata.artifacts must be a list")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and str(artifact.get("artifactKey") or "") == artifact_key
    ]
    if len(matches) != 1:
        raise ValueError(f"metadata must include exactly one {artifact_key} artifact")
    return matches[0]


def validate_production_manifest(manifest: dict[str, Any], *, source_commit: str, release_tag: str) -> None:
    if int(manifest.get("schema_version") or 0) != 1:
        raise ValueError("manifest schema_version must be 1")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("manifest artifacts must be an object")
    for artifact_key in sorted(REQUIRED_ARTIFACT_KEYS):
        spec = artifacts.get(artifact_key)
        if not isinstance(spec, dict):
            raise ValueError(f"manifest missing artifact: {artifact_key}")
        platform = str(spec.get("default_platform") or "").strip()
        if not platform:
            raise ValueError(f"{artifact_key} missing default_platform")
        for field in PRODUCTION_REQUIRED_FIELDS:
            value = map_value(spec, field, platform, artifact_key=artifact_key)
            if isinstance(value, str):
                if value.startswith("pending:") or "pending-release-asset:" in value:
                    raise ValueError(f"{artifact_key}/{platform} has pending production field: {field}")
                if field in {"download_urls", "sbom_urls"} and not GITHUB_RELEASE_ASSET_RE.fullmatch(value):
                    raise ValueError(f"{artifact_key}/{platform} {field} must be a GitHub Release asset API URL")
        if map_value(spec, "source_refs", platform, artifact_key=artifact_key) != source_commit:
            raise ValueError(f"{artifact_key}/{platform} source_refs mismatch")
        if map_value(spec, "source_commits", platform, artifact_key=artifact_key) != source_commit:
            raise ValueError(f"{artifact_key}/{platform} source_commits mismatch")
        builder_id = map_value(spec, "builder_ids", platform, artifact_key=artifact_key)
        if ".github/workflows/release-remote-runner-artifacts.yml@" not in builder_id:
            raise ValueError(f"{artifact_key}/{platform} builder_id does not reference release workflow")
    tag_commit = git_commit(release_tag)
    if tag_commit != source_commit:
        raise ValueError(f"release tag {release_tag} does not resolve to source commit")


def map_value(spec: dict[str, Any], field: str, platform: str, *, artifact_key: str) -> Any:
    mapping = spec.get(field)
    if not isinstance(mapping, dict):
        raise ValueError(f"{artifact_key}/{platform} missing map: {field}")
    value = mapping.get(platform)
    if value is None or value == "":
        raise ValueError(f"{artifact_key}/{platform} missing value: {field}")
    return value


def build_summary(
    *,
    ok: bool,
    args: argparse.Namespace,
    checks: list[dict[str, Any]],
    candidate_manifest: Path | None = None,
    applied_manifest: Path | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "h2ometa-remote-runner-release-promotion.v1",
        "ok": ok,
        "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releaseTag": str(args.release_tag),
        "checks": checks,
    }
    if source_commit:
        payload["sourceCommit"] = source_commit
    if candidate_manifest is not None:
        payload["candidateManifest"] = str(candidate_manifest)
    if applied_manifest is not None:
        payload["appliedManifest"] = str(applied_manifest)
    return payload


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_commit(raw: object, field: str) -> str:
    value = str(raw or "").strip().lower()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a full 40-character commit SHA")
    return value


def require_sha256(raw: object, field: str) -> str:
    value = str(raw or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value


def git_commit(ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ValueError(detail or f"git ref not found: {ref}")
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
