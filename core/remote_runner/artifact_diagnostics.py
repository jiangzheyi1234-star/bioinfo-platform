from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from core.remote_runner.artifact_io import candidate_roots, sha256_file
from core.remote_runner.release_manifest import ReleaseArtifactSpec


def build_artifact_resolution_diagnostics(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    repo_root: Path,
    search_roots: list[Path] | None,
) -> dict[str, Any]:
    filename = f"{spec.name}-{version}-{platform}.tar.gz"
    explicit = str(os.environ.get(spec.bundle_env_var, "") or "").strip()
    roots = candidate_roots(spec, repo_root=repo_root, search_roots=search_roots)
    candidates = [_candidate_status(root / filename) for root in roots]
    explicit_candidate = _candidate_status(Path(explicit)) if explicit else None
    expected_sha256 = str(spec.sha256.get(platform) or "").strip().lower()
    expected_size = int(spec.size_bytes.get(platform) or 0)
    supply_chain = supply_chain_metadata(spec, platform=platform)
    matching_candidate = next(
        (
            item
            for item in ([explicit_candidate] if explicit_candidate else []) + candidates
            if item
            and item["exists"]
            and (not expected_sha256 or item.get("sha256") == expected_sha256)
            and (not expected_size or item.get("sizeBytes") == expected_size)
        ),
        None,
    )
    return {
        "ok": matching_candidate is not None,
        "artifactKey": spec.key,
        "filename": filename,
        "version": version,
        "platform": platform,
        "bundleEnvVar": spec.bundle_env_var,
        "bundleEnvValue": explicit,
        "searchRootEnvVars": list(spec.search_root_env_vars),
        "searchRoots": [str(root) for root in roots],
        "expectedSha256": expected_sha256,
        "expectedSizeBytes": expected_size,
        "supplyChain": supply_chain,
        "explicitCandidate": explicit_candidate,
        "candidates": candidates,
        "resolvedPath": str(matching_candidate["path"]) if matching_candidate else "",
    }


def summarize_artifact_resolution_diagnostics(diagnostics: dict[str, Any]) -> str:
    bundle_env = str(diagnostics.get("bundleEnvVar") or "")
    bundle_value = str(diagnostics.get("bundleEnvValue") or "") or "<unset>"
    roots = diagnostics.get("searchRoots") if isinstance(diagnostics.get("searchRoots"), list) else []
    roots_text = "|".join(str(root) for root in roots) if roots else "<none>"
    return "; ".join(
        (
            f"filename={diagnostics.get('filename') or ''}",
            f"platform={diagnostics.get('platform') or ''}",
            f"searchRoots={roots_text}",
            f"{bundle_env}={bundle_value}",
            f"expectedSha256={diagnostics.get('expectedSha256') or ''}",
            f"resolvedPath={diagnostics.get('resolvedPath') or ''}",
        )
    )


def _candidate_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": exists,
    }
    if exists and path.is_file():
        payload["sizeBytes"] = path.stat().st_size
        payload["sha256"] = sha256_file(path)
    return payload


def supply_chain_metadata(spec: ReleaseArtifactSpec, *, platform: str) -> dict[str, Any]:
    fields = {
        "sbomUrl": str(spec.sbom_urls.get(platform) or "").strip(),
        "provenanceUrl": str(spec.provenance_urls.get(platform) or "").strip(),
        "attestationUrl": str(spec.attestation_urls.get(platform) or "").strip(),
        "signatureUrl": str(spec.signature_urls.get(platform) or "").strip(),
        "builderId": str(spec.builder_ids.get(platform) or "").strip(),
        "sourceRef": str(spec.source_refs.get(platform) or "").strip(),
        "sourceCommit": str(spec.source_commits.get(platform) or "").strip(),
    }
    pending_fields = [
        key
        for key, value in fields.items()
        if value.startswith("pending:") or value == "pending"
    ]
    missing_required = [
        key
        for key in ("sbomUrl", "builderId", "sourceRef")
        if not fields[key]
    ]
    if not fields["sourceCommit"]:
        missing_required.append("sourceCommit")
    if not fields["provenanceUrl"] and not fields["attestationUrl"]:
        missing_required.append("provenanceUrl|attestationUrl")
    if not fields["signatureUrl"] and not fields["attestationUrl"]:
        missing_required.append("signatureUrl|attestationUrl")
    invalid_fields = [
        key
        for key in ("sourceRef", "sourceCommit")
        if fields[key] and not re.fullmatch(r"[0-9a-fA-F]{40}", fields[key])
    ]
    return {
        **fields,
        "complete": len(missing_required) == 0 and len(pending_fields) == 0 and len(invalid_fields) == 0,
        "missingRequired": missing_required,
        "pendingFields": pending_fields,
        "invalidFields": invalid_fields,
        "missingOptional": [],
    }
