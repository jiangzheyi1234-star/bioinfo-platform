from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
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
    rejected_candidates: list[dict[str, Any]] = []
    for root in roots:
        path = root / filename
        if path.exists():
            rejection = declared_artifact_rejection(
                spec,
                version=version,
                platform=platform,
                archive_path=path,
            )
            if rejection:
                rejected_candidates.append(rejection)
                continue
            if version == spec.version:
                expected_sha = str(spec.sha256.get(platform) or "").strip().lower()
                if expected_sha:
                    write_checksum_file(path, expected_sha)
            return path
    try:
        downloaded = download_declared_archive(spec, version=version, platform=platform, filename=filename)
    except RemoteRunnerArtifactError as exc:
        if rejected_candidates:
            raise RemoteRunnerArtifactError(
                f"{exc}; rejected local candidates: {format_rejected_candidates(rejected_candidates)}"
            ) from exc
        raise
    if downloaded is not None:
        return downloaded
    roots_display = ", ".join(str(root) for root in roots)
    rejected = (
        f"; rejected local candidates: {format_rejected_candidates(rejected_candidates)}"
        if rejected_candidates
        else ""
    )
    raise RemoteRunnerArtifactError(
        f"{spec.key.replace('_', ' ')} artifact not found for version {version}; searched: {roots_display}{rejected}"
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
        if cached_declared_archive_is_valid(
            archive_path,
            expected_sha=expected_sha,
            expected_size=expected_size,
        ):
            write_checksum_file(archive_path, expected_sha)
            return archive_path
        archive_path.unlink()

    tmp_path = archive_path.parent / f".download-{os.getpid()}-{uuid.uuid4().hex[:12]}.tmp"
    label = spec.key.replace("_", " ")
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers=download_headers())
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
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
        try:
            os.replace(tmp_path, archive_path)
        except OSError as exc:
            if cached_declared_archive_is_valid(
                archive_path,
                expected_sha=expected_sha,
                expected_size=expected_size,
            ):
                cleanup_download_temp_file(tmp_path)
                write_checksum_file(archive_path, expected_sha)
                return archive_path
            raise RemoteRunnerArtifactError(
                f"{label} artifact cache finalization failed: {type(exc).__name__}: {exc}"
            ) from exc
        write_checksum_file(archive_path, expected_sha)
        return archive_path
    except RemoteRunnerArtifactError:
        raise
    except HTTPError as exc:
        raise RemoteRunnerArtifactError(
            f"{label} artifact download failed from {url} with HTTP {exc.code}; "
            "for private GitHub releases set H2OMETA_RELEASE_DOWNLOAD_TOKEN, GH_TOKEN, GITHUB_TOKEN, "
            "GITHUB_PERSONAL_ACCESS_TOKEN, or configure GH CLI auth with scripts\\configure-github-release-auth.ps1"
        ) from exc
    except (OSError, URLError) as exc:
        raise RemoteRunnerArtifactError(
            f"{label} artifact download failed from {url}: {type(exc).__name__}: {exc}; "
            "for private GitHub releases set H2OMETA_RELEASE_DOWNLOAD_TOKEN, GH_TOKEN, GITHUB_TOKEN, "
            "GITHUB_PERSONAL_ACCESS_TOKEN, or configure GH CLI auth with scripts\\configure-github-release-auth.ps1"
        ) from exc
    finally:
        cleanup_download_temp_file(tmp_path)


def cached_declared_archive_is_valid(
    archive_path: Path,
    *,
    expected_sha: str,
    expected_size: int,
) -> bool:
    if not archive_path.exists():
        return False
    try:
        actual_size = archive_path.stat().st_size
        if expected_size and actual_size != expected_size:
            return False
        return sha256_file(archive_path) == expected_sha
    except OSError:
        return False


def cleanup_download_temp_file(tmp_path: Path) -> None:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        return


def artifact_cache_root() -> Path:
    explicit = str(os.environ.get("H2OMETA_ARTIFACT_CACHE_DIR", "") or "").strip()
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            return Path(local_app_data) / "H2OMeta" / "dev-cache" / "artifacts"
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
        or str(os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "") or "").strip()
        or github_cli_auth_token()
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@lru_cache(maxsize=1)
def github_cli_auth_token() -> str:
    gh = shutil.which("gh")
    if not gh:
        return ""
    env = dict(os.environ)
    gh_config_dir = str(env.get("GH_CONFIG_DIR") or "").strip()
    if not gh_config_dir:
        gh_config_dir = str(env.get("H2OMETA_GH_CONFIG_DIR") or "").strip()
    if not gh_config_dir and os.name == "nt":
        local_app_data = str(env.get("LOCALAPPDATA") or "").strip()
        if local_app_data:
            candidate = Path(local_app_data) / "H2OMeta" / "gh-cli"
            if candidate.exists():
                gh_config_dir = str(candidate)
    if gh_config_dir:
        env["GH_CONFIG_DIR"] = gh_config_dir
    try:
        result = subprocess.run(
            [gh, "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            check=False,
            env=env,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0].strip()


def write_checksum_file(path: Path, sha256: str) -> None:
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    try:
        checksum_path.write_text(
            f"{sha256}  {path.name}\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise RemoteRunnerArtifactError(
            f"artifact checksum cache write failed: {checksum_path}; "
            "set H2OMETA_ARTIFACT_CACHE_DIR to a writable cache directory"
        ) from exc


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


def declared_artifact_rejection(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    archive_path: Path,
) -> dict[str, Any] | None:
    if version != spec.version:
        return None
    declared_sha = str(spec.sha256.get(platform) or "").strip().lower()
    declared_size = int(spec.size_bytes.get(platform) or 0)
    if not declared_sha and not declared_size:
        return None
    actual_size = archive_path.stat().st_size
    actual_sha = sha256_file(archive_path)
    reasons: list[str] = []
    if declared_sha and actual_sha != declared_sha:
        reasons.append("sha256")
    if declared_size and actual_size != declared_size:
        reasons.append("size")
    if not reasons:
        return None
    return {
        "path": str(archive_path),
        "reason": "+".join(reasons),
        "actualSha256": actual_sha,
        "expectedSha256": declared_sha,
        "actualSizeBytes": actual_size,
        "expectedSizeBytes": declared_size,
    }


def format_rejected_candidates(candidates: list[dict[str, Any]]) -> str:
    return "; ".join(
        (
            f"{item.get('path')}"
            f" reason={item.get('reason')}"
            f" actualSha256={item.get('actualSha256')}"
            f" expectedSha256={item.get('expectedSha256')}"
            f" actualSizeBytes={item.get('actualSizeBytes')}"
            f" expectedSizeBytes={item.get('expectedSizeBytes')}"
        )
        for item in candidates
    )


def is_declared_release_artifact(
    spec: ReleaseArtifactSpec,
    *,
    version: str,
    platform: str,
    archive_path: Path,
    repo_root: Path,
) -> bool:
    return version == spec.version and bool(spec.sha256.get(platform) or spec.size_bytes.get(platform))


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
