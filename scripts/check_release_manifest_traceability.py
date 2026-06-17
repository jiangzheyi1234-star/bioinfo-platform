#!/usr/bin/env python3
"""Check that the runtime release manifest is traceable to Git and Release assets."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "config" / "remote-runner-release-manifest.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GITHUB_RELEASE_ASSET_RE = re.compile(r"^https://api\.github\.com/repos/[^/]+/[^/]+/releases/assets/\d+$")
RELEASE_TAG_RE = re.compile(r"^h2ometa-runtime-v[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$")


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"manifest must be a JSON object: {path}")
    return payload


def git_stdout(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def git_commit(ref: str) -> str:
    resolved = git_stdout(["rev-parse", "--verify", f"{ref}^{{commit}}"])
    git_stdout(["cat-file", "-e", f"{resolved}^{{commit}}"])
    return resolved


def git_ref_exists(ref: str) -> bool:
    try:
        git_commit(ref)
    except RuntimeError:
        return False
    return True


def check_text_map(
    spec: dict[str, Any],
    field: str,
    platform: str,
    errors: list[str],
    *,
    artifact_key: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    mapping = spec.get(field)
    if not isinstance(mapping, dict):
        errors.append(f"{artifact_key}/{platform} missing map: {field}")
        return ""
    value = str(mapping.get(platform) or "").strip()
    if not value:
        errors.append(f"{artifact_key}/{platform} missing value: {field}")
        return ""
    if pattern is not None and not pattern.fullmatch(value):
        errors.append(f"{artifact_key}/{platform} invalid {field}: {value}")
    return value


def check_positive_size(spec: dict[str, Any], platform: str, errors: list[str], *, artifact_key: str) -> None:
    mapping = spec.get("size_bytes")
    if not isinstance(mapping, dict):
        errors.append(f"{artifact_key}/{platform} missing map: size_bytes")
        return
    try:
        size = int(mapping.get(platform) or 0)
    except (TypeError, ValueError):
        errors.append(f"{artifact_key}/{platform} invalid size_bytes")
        return
    if size <= 0:
        errors.append(f"{artifact_key}/{platform} size_bytes must be positive")


def check_source_commit(
    *,
    artifact_key: str,
    platform: str,
    source_ref: str,
    source_commit: str,
    release_tag: str,
    errors: list[str],
) -> None:
    if not SHA_RE.fullmatch(source_ref):
        errors.append(f"{artifact_key}/{platform} source_refs must be a full 40-character commit SHA: {source_ref}")
    if not SHA_RE.fullmatch(source_commit):
        errors.append(f"{artifact_key}/{platform} source_commits must be a full 40-character commit SHA: {source_commit}")
        return
    if source_ref and source_ref != source_commit:
        errors.append(f"{artifact_key}/{platform} source_refs does not match source_commits")
    if not git_ref_exists(source_commit):
        errors.append(f"{artifact_key}/{platform} source commit is not present in this checkout: {source_commit}")
        return
    resolved = git_commit(source_commit)
    if resolved != source_commit:
        errors.append(f"{artifact_key}/{platform} source commit resolves unexpectedly: {resolved}")
    if release_tag:
        try:
            tag_commit = git_commit(release_tag)
        except RuntimeError as exc:
            errors.append(f"release tag is not present in this checkout: {release_tag}; {exc}")
            return
        if tag_commit != source_commit:
            errors.append(
                f"{artifact_key}/{platform} release tag {release_tag} points at {tag_commit}, "
                f"not manifest source commit {source_commit}"
            )


def platforms_for_spec(spec: dict[str, Any]) -> set[str]:
    platforms: set[str] = set()
    for field in (
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
    ):
        mapping = spec.get(field)
        if isinstance(mapping, dict):
            platforms.update(str(key) for key in mapping if str(key).strip())
    default_platform = str(spec.get("default_platform") or "").strip()
    if default_platform:
        platforms.add(default_platform)
    return platforms


def check_manifest(manifest: dict[str, Any], *, release_tag: str) -> list[str]:
    errors: list[str] = []
    source_commits: set[str] = set()
    if int(manifest.get("schema_version") or 0) != 1:
        errors.append("manifest schema_version must be 1")
    if release_tag and not RELEASE_TAG_RE.fullmatch(release_tag):
        errors.append(f"release tag must match h2ometa-runtime-vX.Y.Z: {release_tag}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        return [*errors, "manifest missing artifacts object"]
    for artifact_key, raw_spec in sorted(artifacts.items()):
        if not isinstance(raw_spec, dict):
            errors.append(f"{artifact_key} spec must be an object")
            continue
        for platform in sorted(platforms_for_spec(raw_spec)):
            check_text_map(raw_spec, "sha256", platform, errors, artifact_key=artifact_key, pattern=SHA256_RE)
            check_positive_size(raw_spec, platform, errors, artifact_key=artifact_key)
            check_text_map(raw_spec, "lock_sha256", platform, errors, artifact_key=artifact_key, pattern=SHA256_RE)
            check_text_map(
                raw_spec,
                "download_urls",
                platform,
                errors,
                artifact_key=artifact_key,
                pattern=GITHUB_RELEASE_ASSET_RE,
            )
            check_text_map(
                raw_spec,
                "sbom_urls",
                platform,
                errors,
                artifact_key=artifact_key,
                pattern=GITHUB_RELEASE_ASSET_RE,
            )
            check_text_map(raw_spec, "provenance_urls", platform, errors, artifact_key=artifact_key)
            check_text_map(raw_spec, "attestation_urls", platform, errors, artifact_key=artifact_key)
            check_text_map(raw_spec, "signature_urls", platform, errors, artifact_key=artifact_key)
            builder_id = check_text_map(raw_spec, "builder_ids", platform, errors, artifact_key=artifact_key)
            if builder_id and ".github/workflows/release-remote-runner-artifacts.yml@" not in builder_id:
                errors.append(f"{artifact_key}/{platform} builder_ids does not reference release workflow: {builder_id}")
            source_ref = check_text_map(raw_spec, "source_refs", platform, errors, artifact_key=artifact_key)
            source_commit = check_text_map(raw_spec, "source_commits", platform, errors, artifact_key=artifact_key)
            if source_commit:
                source_commits.add(source_commit)
            check_source_commit(
                artifact_key=artifact_key,
                platform=platform,
                source_ref=source_ref,
                source_commit=source_commit,
                release_tag=release_tag,
                errors=errors,
            )
    if len(source_commits) > 1:
        errors.append(f"manifest artifacts must share one source commit, got: {', '.join(sorted(source_commits))}")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check runtime release manifest traceability.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--release-tag",
        default="",
        help="Expected local tag for this runtime Release, for example h2ometa-runtime-v0.1.2.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    errors = check_manifest(load_json(manifest_path), release_tag=str(args.release_tag or "").strip())
    payload = {
        "ok": not errors,
        "manifest": str(manifest_path),
        "releaseTag": str(args.release_tag or ""),
        "errors": errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif errors:
        print("RELEASE_TRACEABILITY: failed")
        for error in errors:
            print(f"- {error}")
    else:
        print("RELEASE_TRACEABILITY: ok")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
