#!/usr/bin/env python3
"""Update the remote runner release manifest from CI release metadata."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"JSON file must contain an object: {path}")
    return payload


def artifact_metadata_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit("release metadata missing artifacts list")
    return [item for item in artifacts if isinstance(item, dict)]


def require_text(mapping: dict[str, Any], key: str, *, context: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise SystemExit(f"{context} missing {key}")
    return value


def download_urls_by_artifact(raw: list[str]) -> dict[tuple[str, str], str]:
    return urls_by_artifact(raw, label="download URL")


def sbom_urls_by_artifact(raw: list[str]) -> dict[tuple[str, str], str]:
    return urls_by_artifact(raw, label="SBOM URL")


def urls_by_artifact(raw: list[str], *, label: str) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    for item in raw:
        try:
            artifact_key, platform, url = item.split("=", 2)
        except ValueError as exc:
            raise SystemExit(f"invalid {label} mapping: {item}") from exc
        if not artifact_key.strip() or not platform.strip() or not url.strip():
            raise SystemExit(f"invalid {label} mapping: {item}")
        values[(artifact_key.strip(), platform.strip())] = url.strip()
    return values


def published_assets_by_name(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = payload.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise SystemExit("published assets metadata missing assets object")
    result: dict[str, dict[str, Any]] = {}
    for name, item in assets.items():
        if not isinstance(item, dict):
            raise SystemExit(f"published asset metadata must be an object: {name}")
        asset_name = str(name or "").strip()
        if not asset_name:
            raise SystemExit("published asset metadata contains an empty asset name")
        result[asset_name] = item
    return result


def asset_api_url(asset: dict[str, Any], *, context: str) -> str:
    value = str(asset.get("apiUrl") or "").strip()
    if not value:
        raise SystemExit(f"{context} missing published asset apiUrl")
    return value


def asset_digest_sha256(asset: dict[str, Any], *, context: str) -> str:
    raw = str(asset.get("digest") or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw.removeprefix("sha256:")
    if len(raw) != 64:
        raise SystemExit(f"{context} missing published asset sha256 digest")
    return raw


def asset_size(asset: dict[str, Any], *, context: str) -> int:
    try:
        size = int(asset.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"{context} has invalid published asset size") from exc
    if size <= 0:
        raise SystemExit(f"{context} missing published asset size")
    return size


def expected_artifact_filename(item: dict[str, Any], *, artifact_key: str) -> str:
    filename = Path(require_text(item, "path", context=f"{artifact_key} metadata")).name
    if not filename:
        raise SystemExit(f"{artifact_key} metadata missing artifact filename")
    return filename


def expected_sbom_filename(item: dict[str, Any], *, artifact_key: str) -> str:
    sbom = item.get("sbom") if isinstance(item.get("sbom"), dict) else {}
    filename = Path(require_text(sbom, "path", context=f"{artifact_key} SBOM metadata")).name
    if not filename:
        raise SystemExit(f"{artifact_key} SBOM metadata missing filename")
    return filename


def merge_published_asset_urls(
    *,
    metadata: dict[str, Any],
    published_assets: dict[str, Any] | None,
    download_urls: dict[tuple[str, str], str],
    sbom_urls: dict[tuple[str, str], str],
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    if published_assets is None:
        return download_urls, sbom_urls
    assets = published_assets_by_name(published_assets)
    merged_download_urls = dict(download_urls)
    merged_sbom_urls = dict(sbom_urls)
    for item in artifact_metadata_items(metadata):
        artifact_key = require_text(item, "artifactKey", context="artifact metadata")
        platform = require_text(item, "platform", context=f"{artifact_key} metadata")
        mapping_key = (artifact_key, platform)
        artifact_filename = expected_artifact_filename(item, artifact_key=artifact_key)
        artifact_asset = assets.get(artifact_filename)
        if not artifact_asset:
            raise SystemExit(f"published assets missing artifact: {artifact_filename}")
        expected_sha = require_text(item, "sha256", context=f"{artifact_key} metadata").lower()
        actual_sha = asset_digest_sha256(artifact_asset, context=f"{artifact_key} artifact")
        if actual_sha != expected_sha:
            raise SystemExit(
                f"{artifact_key} published artifact sha256 mismatch: expected {expected_sha}, got {actual_sha}"
            )
        expected_size = int(item.get("sizeBytes") or 0)
        actual_size = asset_size(artifact_asset, context=f"{artifact_key} artifact")
        if expected_size <= 0:
            raise SystemExit(f"{artifact_key} metadata missing sizeBytes")
        if actual_size != expected_size:
            raise SystemExit(
                f"{artifact_key} published artifact size mismatch: expected {expected_size}, got {actual_size}"
            )
        merged_download_urls[mapping_key] = asset_api_url(artifact_asset, context=f"{artifact_key} artifact")

        sbom_filename = expected_sbom_filename(item, artifact_key=artifact_key)
        sbom_asset = assets.get(sbom_filename)
        if not sbom_asset:
            raise SystemExit(f"published assets missing SBOM: {sbom_filename}")
        sbom = item.get("sbom") if isinstance(item.get("sbom"), dict) else {}
        expected_sbom_sha = require_text(sbom, "sha256", context=f"{artifact_key} SBOM metadata").lower()
        actual_sbom_sha = asset_digest_sha256(sbom_asset, context=f"{artifact_key} SBOM")
        if actual_sbom_sha != expected_sbom_sha:
            raise SystemExit(
                f"{artifact_key} published SBOM sha256 mismatch: expected {expected_sbom_sha}, got {actual_sbom_sha}"
            )
        merged_sbom_urls[mapping_key] = asset_api_url(sbom_asset, context=f"{artifact_key} SBOM")
    return merged_download_urls, merged_sbom_urls


def attestation_url(attestations: dict[str, Any], artifact_key: str) -> str:
    if artifact_key == "remote_runner":
        sbom = (attestations.get("sbom") or {}).get("remote_runner") if isinstance(attestations.get("sbom"), dict) else {}
    elif artifact_key == "workflow_runtime":
        sbom = (attestations.get("sbom") or {}).get("workflow_runtime") if isinstance(attestations.get("sbom"), dict) else {}
    else:
        sbom = {}
    provenance = attestations.get("provenance") if isinstance(attestations.get("provenance"), dict) else {}
    for item in (sbom, provenance):
        if isinstance(item, dict):
            url = str(item.get("attestationUrl") or "").strip()
            if url:
                return url
    return ""


def provenance_url(attestations: dict[str, Any]) -> str:
    provenance = attestations.get("provenance") if isinstance(attestations.get("provenance"), dict) else {}
    return str(provenance.get("attestationUrl") or "").strip()


def update_manifest(
    manifest: dict[str, Any],
    *,
    metadata: dict[str, Any],
    attestations: dict[str, Any],
    download_urls: dict[tuple[str, str], str],
    sbom_urls: dict[tuple[str, str], str],
) -> dict[str, Any]:
    updated = deepcopy(manifest)
    artifacts = updated.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SystemExit("release manifest missing artifacts object")
    builder = metadata.get("builder") if isinstance(metadata.get("builder"), dict) else {}
    builder_id = require_text(builder, "id", context="release metadata builder")
    source_ref = require_text(metadata, "sourceRef", context="release metadata")
    source_commit = require_text(metadata, "sourceCommit", context="release metadata")
    provenance = provenance_url(attestations)
    if not provenance:
        raise SystemExit("release attestations missing provenance attestationUrl")
    for item in artifact_metadata_items(metadata):
        artifact_key = require_text(item, "artifactKey", context="artifact metadata")
        platform = require_text(item, "platform", context=f"{artifact_key} metadata")
        spec = artifacts.get(artifact_key)
        if not isinstance(spec, dict):
            raise SystemExit(f"release manifest missing artifact: {artifact_key}")
        lock = item.get("lock") if isinstance(item.get("lock"), dict) else {}
        sbom = item.get("sbom") if isinstance(item.get("sbom"), dict) else {}
        download_url = download_urls.get((artifact_key, platform), "")
        if not download_url:
            raise SystemExit(f"missing download URL for {artifact_key}/{platform}")
        sbom_url = sbom_urls.get((artifact_key, platform), "")
        if not sbom_url:
            raise SystemExit(f"missing SBOM URL for {artifact_key}/{platform}")
        artifact_attestation_url = attestation_url(attestations, artifact_key)
        if not artifact_attestation_url:
            raise SystemExit(f"release attestations missing attestationUrl for {artifact_key}")
        spec.setdefault("sha256", {})[platform] = require_text(item, "sha256", context=f"{artifact_key} metadata")
        spec.setdefault("size_bytes", {})[platform] = int(item.get("sizeBytes") or 0)
        spec.setdefault("lock_sha256", {})[platform] = require_text(lock, "sha256", context=f"{artifact_key} lock metadata")
        spec.setdefault("download_urls", {})[platform] = download_url
        require_text(sbom, "sha256", context=f"{artifact_key} SBOM metadata")
        spec.setdefault("sbom_urls", {})[platform] = sbom_url
        spec.setdefault("provenance_urls", {})[platform] = provenance
        spec.setdefault("attestation_urls", {})[platform] = artifact_attestation_url
        spec.setdefault("signature_urls", {})[platform] = spec["attestation_urls"][platform]
        spec.setdefault("builder_ids", {})[platform] = builder_id
        spec.setdefault("source_refs", {})[platform] = require_text(
            {"sourceRef": item.get("sourceRef") or source_ref},
            "sourceRef",
            context=f"{artifact_key} metadata",
        )
        spec.setdefault("source_commits", {})[platform] = require_text(
            {"sourceCommit": item.get("sourceCommit") or source_commit},
            "sourceCommit",
            context=f"{artifact_key} metadata",
        )
    return updated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update remote runner release manifest from CI metadata.")
    parser.add_argument("--manifest", default=str(REPO_ROOT / "config" / "remote-runner-release-manifest.json"))
    parser.add_argument("--metadata", required=True, help="Path to release-artifacts-metadata.json.")
    parser.add_argument("--attestations", required=True, help="Path to release-attestations.json.")
    parser.add_argument(
        "--published-assets",
        default="",
        help="Path to release-published-assets.json emitted by the publish job.",
    )
    parser.add_argument(
        "--download-url",
        action="append",
        default=[],
        help="Artifact download URL mapping in artifact_key=platform=url form.",
    )
    parser.add_argument(
        "--sbom-url",
        action="append",
        default=[],
        help="Published SBOM URL mapping in artifact_key=platform=url form.",
    )
    parser.add_argument("--output", default="", help="Write to this path instead of updating --manifest.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    output_path = Path(args.output) if args.output else manifest_path
    metadata = load_json(Path(args.metadata))
    published_assets = load_json(Path(args.published_assets)) if args.published_assets else None
    download_urls, sbom_urls = merge_published_asset_urls(
        metadata=metadata,
        published_assets=published_assets,
        download_urls=download_urls_by_artifact(list(args.download_url or [])),
        sbom_urls=sbom_urls_by_artifact(list(args.sbom_url or [])),
    )
    updated = update_manifest(
        load_json(manifest_path),
        metadata=metadata,
        attestations=load_json(Path(args.attestations)),
        download_urls=download_urls,
        sbom_urls=sbom_urls,
    )
    output_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
