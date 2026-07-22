from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile

from core.remote_runner.artifact import RemoteRunnerArtifactProvider
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields
from core.remote_runner.release_manifest import ReleaseArtifactSpec


def add_packaged_sqlite_metadata(archive: tarfile.TarFile) -> None:
    payload = json.dumps(
        {"name": "libsqlite", "version": "3.53.0", "build": "hf4e2dac_0"}
    ).encode("utf-8")
    info = tarfile.TarInfo("runtime/conda-meta/libsqlite-3.53.0-hf4e2dac_0.json")
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def write_remote_runner_artifact(
    path: Path,
    *,
    version: str = "0.1.0-control-plane",
    platform: str = "linux-64",
    content: bytes = b"artifact",
    include_wrapper_assets: bool = True,
    runtime_python_mode: int = 0o755,
    include_runner_protocol: bool = True,
    runner_protocol_fingerprint: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "service": "h2ometa-remote",
        "version": version,
        "platform": platform,
        "runtime": {
            "provider": "bundled",
            "python": "runtime/bin/python",
            "sqlite": {"minimumVersion": "3.51.3"},
        },
    }
    if include_runner_protocol:
        manifest.update(build_runner_protocol_manifest_fields())
        if runner_protocol_fingerprint is not None:
            manifest["runnerProtocolFingerprint"] = runner_protocol_fingerprint
    with tarfile.open(path, "w:gz") as archive:
        _add_bytes(archive, "bootstrap_manifest.json", json.dumps(manifest).encode())
        _add_bytes(archive, "payload.txt", content)
        python_link = tarfile.TarInfo("runtime/bin/python")
        python_link.type = tarfile.SYMTYPE
        python_link.mode = 0o777
        python_link.linkname = "python3.12"
        archive.addfile(python_link)
        _add_bytes(
            archive,
            "runtime/bin/python3.12",
            b"#!/usr/bin/env python\n",
            mode=runtime_python_mode,
        )
        _add_bytes(
            archive,
            "runtime/bin/conda-unpack",
            b"#!/usr/bin/env python\n",
            mode=0o755,
        )
        add_packaged_sqlite_metadata(archive)
        if include_wrapper_assets:
            for name in RemoteRunnerArtifactProvider.REQUIRED_WRAPPER_ASSET_MEMBERS:
                _add_bytes(archive, name, b"placeholder\n")
    payload = path.read_bytes()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )


def _add_bytes(
    archive: tarfile.TarFile,
    name: str,
    payload: bytes,
    *,
    mode: int = 0o644,
) -> None:
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def staged_artifact_matches_manifest(
    bundle: Path, spec: ReleaseArtifactSpec, *, platform: str
) -> bool:
    expected_sha = str(spec.sha256.get(platform) or "").strip()
    expected_size = int(spec.size_bytes.get(platform) or 0)
    if expected_sha and hashlib.sha256(bundle.read_bytes()).hexdigest() != expected_sha:
        return False
    return not expected_size or bundle.stat().st_size == expected_size
