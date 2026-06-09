from __future__ import annotations

import hashlib
from pathlib import Path

from core.remote_runner.release_manifest import ReleaseArtifactSpec


def staged_artifact_matches_manifest(bundle: Path, spec: ReleaseArtifactSpec, *, platform: str) -> bool:
    expected_sha = str(spec.sha256.get(platform) or "").strip()
    expected_size = int(spec.size_bytes.get(platform) or 0)
    if expected_sha and hashlib.sha256(bundle.read_bytes()).hexdigest() != expected_sha:
        return False
    return not expected_size or bundle.stat().st_size == expected_size
