from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from core.remote_runner.artifact_models import RemoteRunnerArtifactError
from core.remote_runner.release_manifest import RELEASE_MANIFEST, ReleaseArtifactSpec


def resolve_archive_path(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    repo_root: Path,
    search_roots: list[Path] | None,
) -> Path:
    explicit = str(os.environ.get(spec.bundle_env_var, "") or "").strip()
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise RemoteRunnerArtifactError(f"{spec.key.replace('_', ' ')} artifact not found: {path}")
        return path

    filename = f"{spec.name}-{version}-{platform}.tar.gz"
    roots = candidate_roots(spec, repo_root=repo_root, search_roots=search_roots)
    for root in roots:
        path = root / filename
        if path.exists():
            return path
    downloaded = download_declared_archive(spec, version=version, platform=platform, filename=filename)
    if downloaded is not None:
        return downloaded
    roots_display = ", ".join(str(root) for root in roots)
    raise RemoteRunnerArtifactError(
        f"{spec.key.replace('_', ' ')} artifact not found for version {version}; searched: {roots_display}"
    )


def download_declared_archive(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    filename: str,
) -> Path | None:
    if version != spec.version:
        return None
    url = str(spec.download_urls.get(platform) or "").strip()
    if not url:
        return None
    expected_sha = str(spec.sha256.get(platform) or "").strip().lower()
    if len(expected_sha) != 64:
        raise RemoteRunnerArtifactError(
            f"{spec.key.replace('_', ' ')} artifact download is missing manifest sha256 for {platform}"
        )
    expected_size = int(spec.size_bytes.get(platform) or 0)
    cache_dir = artifact_cache_root() / spec.key / version / platform
    archive_path = cache_dir / filename
    if archive_path.exists():
        actual_sha = sha256_file(archive_path)
        actual_size = archive_path.stat().st_size
        if actual_sha == expected_sha and (not expected_size or actual_size == expected_size):
            write_checksum_file(archive_path, expected_sha)
            return archive_path
        archive_path.unlink()

    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = archive_path.with_name(f"{archive_path.name}.tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    label = spec.key.replace("_", " ")
    try:
        request = Request(url, headers=download_headers())
        with urlopen(request, timeout=120) as response, tmp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        actual_size = tmp_path.stat().st_size
        if expected_size and actual_size != expected_size:
            raise RemoteRunnerArtifactError(
                f"{label} artifact size mismatch after download: expected {expected_size}, got {actual_size}"
            )
        actual_sha = sha256_file(tmp_path)
        if actual_sha != expected_sha:
            raise RemoteRunnerArtifactError(f"{label} artifact sha256 mismatch after download: {url}")
        os.replace(tmp_path, archive_path)
        write_checksum_file(archive_path, expected_sha)
        return archive_path
    except RemoteRunnerArtifactError:
        raise
    except (OSError, URLError) as exc:
        raise RemoteRunnerArtifactError(
            f"{label} artifact download failed from {url}; "
            "for private GitHub releases set H2OMETA_RELEASE_DOWNLOAD_TOKEN, GH_TOKEN, or GITHUB_TOKEN"
        ) from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def artifact_cache_root() -> Path:
    explicit = str(os.environ.get("H2OMETA_ARTIFACT_CACHE_DIR", "") or "").strip()
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            return Path(local_app_data) / "H2OMeta" / "artifacts"
    xdg_cache_home = str(os.environ.get("XDG_CACHE_HOME", "") or "").strip()
    return (Path(xdg_cache_home) if xdg_cache_home else Path.home() / ".cache") / "h2ometa" / "artifacts"


def download_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "h2ometa-artifact-provider",
    }
    token = (
        str(os.environ.get("H2OMETA_RELEASE_DOWNLOAD_TOKEN", "") or "").strip()
        or str(os.environ.get("GH_TOKEN", "") or "").strip()
        or str(os.environ.get("GITHUB_TOKEN", "") or "").strip()
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def write_checksum_file(path: Path, sha256: str) -> None:
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{sha256}  {path.name}\n",
        encoding="utf-8",
    )


def candidate_roots(
    spec: ReleaseArtifactSpec,
    *,
    repo_root: Path,
    search_roots: list[Path] | None,
) -> list[Path]:
    if search_roots is not None:
        return list(search_roots)
    roots: list[Path] = []
    for key in spec.search_root_env_vars:
        raw = str(os.environ.get(key, "") or "").strip()
        if raw:
            roots.append(Path(raw))
    resources_root = str(os.environ.get("H2OMETA_RESOURCES_DIR", "") or "").strip()
    if resources_root:
        roots.append(Path(resources_root) / "remote-runner")
    roots.extend(RELEASE_MANIFEST.repo_search_roots(repo_root))
    return roots


def read_expected_sha256(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    expected = raw.split()[0] if raw else ""
    if len(expected) != 64:
        raise RemoteRunnerArtifactError(f"remote runner artifact checksum is invalid: {path}")
    return expected.lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_declared_artifact_metadata(
    spec: ReleaseArtifactSpec,
    *,
    platform: str,
    archive_path: Path,
    sha256: str,
) -> None:
    declared_sha = str(spec.sha256.get(platform) or "").strip().lower()
    if declared_sha and declared_sha != sha256:
        raise RemoteRunnerArtifactError(f"{spec.key.replace('_', ' ')} manifest sha256 mismatch: {archive_path}")
    declared_size = int(spec.size_bytes.get(platform) or 0)
    if declared_size and declared_size != archive_path.stat().st_size:
        raise RemoteRunnerArtifactError(f"{spec.key.replace('_', ' ')} manifest size mismatch: {archive_path}")


def is_declared_release_artifact(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    archive_path: Path,
    repo_root: Path,
) -> bool:
    if version != spec.version or archive_path.name != spec.archive_filename(platform):
        return False
    resolved_path = archive_path.resolve()
    for root in RELEASE_MANIFEST.repo_search_roots(repo_root):
        if resolved_path == (root / spec.archive_filename(platform)).resolve():
            return True
    return False


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            validated_member_names(archive, path)
            member = next(
                (
                    item
                    for item in archive.getmembers()
                    if item.name.strip("./") == "bootstrap_manifest.json"
                ),
                None,
            )
            if member is None:
                raise RemoteRunnerArtifactError(f"remote runner artifact manifest not found: {path}")
            handle = archive.extractfile(member)
            if handle is None:
                raise RemoteRunnerArtifactError(f"remote runner artifact manifest is unreadable: {path}")
            payload = json.loads(handle.read().decode("utf-8"))
    except RemoteRunnerArtifactError:
        raise
    except (OSError, EOFError, tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteRunnerArtifactError(f"remote runner artifact manifest is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise RemoteRunnerArtifactError(f"remote runner artifact manifest is not an object: {path}")
    return payload


def validated_member_names(archive: tarfile.TarFile, path: Path) -> set[str]:
    names: set[str] = set()
    for item in archive.getmembers():
        raw_name = item.name.replace("\\", "/")
        if raw_name in {".", "./"}:
            continue
        posix_name = PurePosixPath(raw_name)
        if raw_name.startswith("/") or posix_name.is_absolute() or ".." in posix_name.parts:
            raise RemoteRunnerArtifactError(f"remote runner artifact has unsafe tar member: {path}")
        name = raw_name.strip("./")
        if not name:
            raise RemoteRunnerArtifactError(f"remote runner artifact has unsafe tar member: {path}")
        names.add(name)
    return names
