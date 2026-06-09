#!/usr/bin/env python3
"""Build release artifacts on a controlled Linux CI builder.

This script is intentionally separate from the SSH builder scripts. The SSH
builders are useful for development and repair; production release artifacts
should be produced by CI from an immutable source ref.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.release_manifest import (  # noqa: E402
    REMOTE_RUNNER_ARTIFACT,
    REMOTE_RUNNER_VERSION,
    WORKFLOW_RUNTIME_ARTIFACT,
    WORKFLOW_RUNTIME_VERSION,
)
from scripts import build_remote_runner_artifact_on_server as runner_builder  # noqa: E402
from scripts import build_workflow_runtime_artifact_on_server as workflow_builder  # noqa: E402

ATTESTATION_BUNDLE_FILENAMES = {
    "provenance": "release-provenance.intoto.json",
    "remote_runner": "h2ometa-remote-runner-sbom.intoto.json",
    "workflow_runtime": "h2ometa-workflow-runtime-sbom.intoto.json",
}

CORE_RUNTIME_HELPER_FILES = (
    "async_boundary.py",
    "api_payloads.py",
    "api_responses.py",
    "problem_responses.py",
    "problem_status.py",
)


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git(args: list[str], *, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=not binary,
    )
    return result.stdout


def git_file_bytes(source_ref: str, repo_relative_path: str) -> bytes:
    return run_git(["show", f"{source_ref}:{repo_relative_path}"], binary=True)


def git_file_text(source_ref: str, repo_relative_path: str) -> str:
    return git_file_bytes(source_ref, repo_relative_path).decode("utf-8")


def git_commit(ref: str) -> str:
    return str(run_git(["rev-parse", f"{ref}^{{commit}}"])).strip()


def git_worktree_is_clean() -> bool:
    return str(run_git(["status", "--porcelain=v1"])).strip() == ""


def git_ref_type(ref: str) -> str:
    return str(run_git(["cat-file", "-t", ref])).strip()


def source_ref_is_immutable(source_ref: str) -> bool:
    try:
        if re.fullmatch(r"[0-9a-fA-F]{40}", source_ref):
            return git_ref_type(source_ref) == "commit"
    except subprocess.CalledProcessError:
        return False
    return False


def ensure_source_ref_checked_out(source_ref: str) -> str:
    if not source_ref:
        raise SystemExit("CI release artifact builds require --source-ref or GITHUB_SHA.")
    if not source_ref_is_immutable(source_ref):
        raise SystemExit(
            "CI release artifact builds require an immutable --source-ref: "
            "use a full 40-character commit SHA, not a branch, tag, or short ref."
        )
    expected = git_commit(source_ref)
    actual = git_commit("HEAD")
    if expected != actual:
        raise SystemExit(
            f"CI release artifact build source ref is not checked out: expected {expected}, HEAD is {actual}"
        )
    if not git_worktree_is_clean():
        raise SystemExit("CI release artifact build requires a clean git worktree.")
    return expected


def copy_git_file(source_ref: str, repo_relative_path: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(git_file_bytes(source_ref, repo_relative_path))


def git_release_files_at_ref(local_dir: Path, source_ref: str) -> list[str]:
    release_root = local_dir.relative_to(REPO_ROOT).as_posix()
    result = run_git(["ls-tree", "-r", "--name-only", source_ref, "--", release_root])
    files: list[str] = []
    for raw in str(result).splitlines():
        repo_relative_path = raw.strip()
        if repo_relative_path:
            files.append(repo_relative_path)
    return files


def copy_git_tree(local_dir: Path, destination: Path, *, source_ref: str) -> None:
    release_root = local_dir.relative_to(REPO_ROOT).as_posix()
    for repo_relative_path in git_release_files_at_ref(local_dir, source_ref):
        parts = PurePosixPath(repo_relative_path).parts
        if ".test" in parts and parts[-1] != "run-config.json":
            continue
        rel = PurePosixPath(repo_relative_path).relative_to(PurePosixPath(release_root))
        target = destination.joinpath(*rel.parts)
        copy_git_file(source_ref, repo_relative_path, target)


def copy_remote_runner_sources(build_root: Path, *, source_ref: str) -> None:
    copy_git_tree(
        REPO_ROOT / "apps" / "remote_runner",
        build_root / "bundle" / "remote_runner",
        source_ref=source_ref,
    )
    copy_git_file(source_ref, "core/__init__.py", build_root / "bundle" / "core" / "__init__.py")
    for filename in CORE_RUNTIME_HELPER_FILES:
        copy_git_file(source_ref, f"core/{filename}", build_root / "bundle" / "core" / filename)
    copy_git_tree(
        REPO_ROOT / "core" / "contracts",
        build_root / "bundle" / "core" / "contracts",
        source_ref=source_ref,
    )


def materialize_lock_file(spec, *, platform: str, source_ref: str, build_root: Path) -> Path:
    relative = spec.conda_explicit_specs.get(platform)
    if not relative:
        raise SystemExit(f"{spec.key} manifest has no explicit conda spec for {platform}")
    text = git_file_text(source_ref, relative)
    first_line = text.splitlines()[0:1]
    if first_line != ["@EXPLICIT"]:
        raise SystemExit(f"{spec.key} explicit conda spec must start with @EXPLICIT: {relative}")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    declared = str(spec.lock_sha256.get(platform) or "").strip().lower()
    if declared and declared != digest:
        raise SystemExit(
            f"{spec.key} explicit conda spec sha256 mismatch at {source_ref}:{relative}: "
            f"expected {declared}, got {digest}"
        )
    path = build_root / "locks" / spec.key / PurePosixPath(relative).name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_bash(script: str, *, build_root: Path | None = None) -> str:
    if os.name == "nt":
        raise SystemExit("CI release artifact builds must run on a Linux builder, not Windows.")
    env = dict(os.environ)
    if build_root is not None:
        env["BUILD_ROOT"] = str(build_root)
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"release artifact build script failed with exit code {result.returncode}")
    return result.stdout


def copy_built_artifact(remote_artifact: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    local_artifact = output_dir / remote_artifact.name
    shutil.copy2(remote_artifact, local_artifact)
    digest = sha256_file(local_artifact)
    checksum_path = Path(str(local_artifact) + ".sha256")
    checksum_path.write_text(f"{digest}  {local_artifact.name}\n", encoding="utf-8")
    return {
        "path": str(local_artifact),
        "sha256Path": str(checksum_path),
        "sha256": digest,
        "sizeBytes": local_artifact.stat().st_size,
    }


def conda_lock_packages(lock_path: Path) -> list[dict[str, str]]:
    packages: list[dict[str, str]] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw == "@EXPLICIT":
            continue
        filename = raw.rsplit("/", 1)[-1]
        package_name = filename
        for suffix in (".conda", ".tar.bz2"):
            if package_name.endswith(suffix):
                package_name = package_name[: -len(suffix)]
                break
        packages.append(
            {
                "name": package_name,
                "url": raw,
                "filename": filename,
            }
        )
    return packages


def write_spdx_sbom(*, artifact: dict[str, Any], output_dir: Path, source_ref: str) -> dict[str, str]:
    artifact_path = Path(str(artifact["path"]))
    lock_path = Path(str((artifact.get("lock") or {}).get("path") or ""))
    dependency_packages = conda_lock_packages(lock_path) if lock_path.exists() else []
    sbom_path = output_dir / f"{artifact_path.name}.spdx.json"
    packages: list[dict[str, Any]] = [
        {
            "name": artifact_path.name,
            "SPDXID": "SPDXRef-ReleaseArtifact",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "checksums": [{"algorithm": "SHA256", "checksumValue": artifact["sha256"]}],
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": (
                        f"pkg:generic/h2ometa/{artifact['artifactKey']}@{artifact['version']}"
                        f"?platform={artifact['platform']}"
                    ),
                }
            ],
            "sourceInfo": f"sourceRef={source_ref}",
        }
    ]
    relationships: list[dict[str, str]] = []
    for index, package in enumerate(dependency_packages, start=1):
        spdx_id = f"SPDXRef-CondaPackage-{index}"
        packages.append(
            {
                "name": package["name"],
                "SPDXID": spdx_id,
                "downloadLocation": package["url"],
                "filesAnalyzed": False,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:generic/conda/{package['name']}",
                    }
                ],
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-ReleaseArtifact",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": spdx_id,
            }
        )
    payload = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"H2OMeta {artifact['artifactKey']} {artifact['version']} {artifact['platform']}",
        "documentNamespace": f"https://h2ometa.local/spdx/{artifact_path.name}/{artifact['sha256']}",
        "creationInfo": {
            "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: h2ometa-build-release-artifacts-in-ci"],
        },
        "packages": packages,
        "relationships": relationships,
    }
    sbom_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "path": str(sbom_path),
        "sha256": sha256_file(sbom_path),
    }


def build_remote_runner_artifact(
    *,
    output_dir: Path,
    platform: str,
    source_ref: str,
    work_root: Path,
    source_commit: str,
) -> dict[str, Any]:
    build_root = work_root / "remote-runner"
    build_root.mkdir(parents=True, exist_ok=True)
    copy_remote_runner_sources(build_root, source_ref=source_ref)
    lock_file = materialize_lock_file(REMOTE_RUNNER_ARTIFACT, platform=platform, source_ref=source_ref, build_root=build_root)
    shutil.copy2(lock_file, build_root / "explicit.txt")
    lock_sha256 = sha256_text(lock_file)
    plan = runner_builder.build_remote_script_plan(
        version=REMOTE_RUNNER_VERSION,
        platform=platform,
        runtime_source="lockfile",
        lock_file_name=lock_file.name,
        lock_sha256=lock_sha256,
    )
    output = run_bash(plan["remoteScript"], build_root=build_root)
    built_path = Path(output.strip().splitlines()[-1].strip())
    artifact = copy_built_artifact(built_path, output_dir)
    artifact.update(
        {
            "artifactKey": REMOTE_RUNNER_ARTIFACT.key,
            "version": REMOTE_RUNNER_VERSION,
            "platform": platform,
            "lock": {"path": str(lock_file), "sha256": lock_sha256},
            "sourceRef": source_ref,
            "sourceCommit": source_commit,
        }
    )
    artifact["sbom"] = write_spdx_sbom(artifact=artifact, output_dir=output_dir, source_ref=source_ref)
    return artifact


def build_workflow_runtime_artifact(
    *,
    output_dir: Path,
    platform: str,
    source_ref: str,
    work_root: Path,
    source_commit: str,
) -> dict[str, Any]:
    build_root = work_root / "workflow-runtime"
    build_root.mkdir(parents=True, exist_ok=True)
    lock_file = materialize_lock_file(
        WORKFLOW_RUNTIME_ARTIFACT,
        platform=platform,
        source_ref=source_ref,
        build_root=build_root,
    )
    shutil.copy2(lock_file, build_root / "explicit.txt")
    lock_sha256 = sha256_text(lock_file)
    plan = workflow_builder.build_remote_script_plan(
        version=WORKFLOW_RUNTIME_VERSION,
        platform=platform,
        snakemake_version="",
        runtime_source="lockfile",
        lock_file_name=lock_file.name,
        lock_sha256=lock_sha256,
    )
    remote_script = plan["remoteScript"].replace(
        'BUILD_ROOT="$(mktemp -d /tmp/h2ometa-workflow-runtime.XXXXXX)"',
        f"BUILD_ROOT={shlex.quote(str(build_root))}",
        1,
    )
    output = run_bash(remote_script)
    built_path = Path(output.strip().splitlines()[-1].strip())
    artifact = copy_built_artifact(built_path, output_dir)
    artifact.update(
        {
            "artifactKey": WORKFLOW_RUNTIME_ARTIFACT.key,
            "version": WORKFLOW_RUNTIME_VERSION,
            "platform": platform,
            "lock": {"path": str(lock_file), "sha256": lock_sha256},
            "sourceRef": source_ref,
            "sourceCommit": source_commit,
        }
    )
    artifact["sbom"] = write_spdx_sbom(
        artifact=artifact,
        output_dir=output_dir,
        source_ref=str(artifact["sourceRef"]),
    )
    return artifact


def build_metadata(*, artifacts: list[dict[str, Any]], source_ref: str, source_commit: str) -> dict[str, Any]:
    server_url = str(os.environ.get("GITHUB_SERVER_URL", "") or "").strip()
    repository = str(os.environ.get("GITHUB_REPOSITORY", "") or "").strip()
    run_id = str(os.environ.get("GITHUB_RUN_ID", "") or "").strip()
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}" if server_url and repository and run_id else ""
    builder_id = str(os.environ.get("GITHUB_WORKFLOW_REF", "") or "").strip()
    return {
        "schemaVersion": "h2ometa-release-artifacts-ci.v1",
        "builder": {
            "type": "github-actions" if builder_id else "local-linux-builder",
            "id": builder_id,
            "runUrl": run_url,
        },
        "sourceRef": source_ref,
        "sourceCommit": source_commit,
        "artifacts": artifacts,
    }


def write_local_attestation_bundle(
    *,
    output_dir: Path,
    filename: str,
    predicate_type: str,
    subject: dict[str, Any],
    predicate: dict[str, Any],
) -> dict[str, str]:
    bundle_dir = output_dir / "attestation-bundles"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    path = bundle_dir / filename
    payload = {
        "schemaVersion": "h2ometa-release-attestation.v1",
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {
                "name": str(subject["name"]),
                "digest": {"sha256": str(subject["sha256"])},
            }
        ],
        "predicateType": predicate_type,
        "predicate": predicate,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
    }


def write_release_attestations(*, metadata: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    builder = metadata.get("builder") if isinstance(metadata.get("builder"), dict) else {}
    source_ref = str(metadata.get("sourceRef") or "").strip()
    source_commit = str(metadata.get("sourceCommit") or "").strip()
    artifacts = [item for item in metadata.get("artifacts") or [] if isinstance(item, dict)]
    subjects = [
        {
            "name": Path(str(item.get("path") or "")).name,
            "sha256": str(item.get("sha256") or "").strip(),
        }
        for item in artifacts
    ]
    provenance = write_local_attestation_bundle(
        output_dir=output_dir,
        filename=ATTESTATION_BUNDLE_FILENAMES["provenance"],
        predicate_type="https://slsa.dev/provenance/v1",
        subject={"name": "h2ometa-remote-runner-release", "sha256": sha256_text(output_dir / "release-artifacts-metadata.json")},
        predicate={
            "buildType": "https://github.com/jiangzheyi1234-star/bioinfo-platform/.github/workflows/release-remote-runner-artifacts.yml",
            "builder": builder,
            "sourceRef": source_ref,
            "sourceCommit": source_commit,
            "runUrl": str(builder.get("runUrl") or ""),
            "materials": [
                {
                    "uri": f"git+https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}@{source_commit}",
                    "digest": {"sha1": source_commit},
                }
            ],
            "subjects": subjects,
        },
    )
    sbom_entries: dict[str, dict[str, str]] = {}
    for item in artifacts:
        artifact_key = str(item.get("artifactKey") or "").strip()
        if artifact_key not in ("remote_runner", "workflow_runtime"):
            continue
        sbom = item.get("sbom") if isinstance(item.get("sbom"), dict) else {}
        bundle = write_local_attestation_bundle(
            output_dir=output_dir,
            filename=ATTESTATION_BUNDLE_FILENAMES[artifact_key],
            predicate_type="https://spdx.dev/Document",
            subject={
                "name": Path(str(item.get("path") or "")).name,
                "sha256": str(item.get("sha256") or "").strip(),
            },
            predicate={
                "artifactKey": artifact_key,
                "platform": str(item.get("platform") or ""),
                "sourceRef": str(item.get("sourceRef") or source_ref),
                "sourceCommit": str(item.get("sourceCommit") or source_commit),
                "sbomPath": str(sbom.get("path") or ""),
                "sbomSha256": str(sbom.get("sha256") or ""),
            },
        )
        sbom_entries[artifact_key] = {
            "attestationId": bundle["sha256"],
            "attestationUrl": f"pending-release-asset:{Path(bundle['path']).name}",
            "bundlePath": bundle["path"],
            "bundleSha256": bundle["sha256"],
        }
    payload = {
        "schemaVersion": "h2ometa-release-attestations.v1",
        "platform": str(artifacts[0].get("platform") or "") if artifacts else "",
        "provenance": {
            "attestationId": provenance["sha256"],
            "attestationUrl": f"pending-release-asset:{Path(provenance['path']).name}",
            "bundlePath": provenance["path"],
            "bundleSha256": provenance["sha256"],
        },
        "sbom": sbom_entries,
    }
    path = output_dir / "release-attestations.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def release_manifest_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    builder = metadata.get("builder") if isinstance(metadata.get("builder"), dict) else {}
    builder_id = str(builder.get("id") or "").strip()
    result: dict[str, Any] = {
        "schemaVersion": "h2ometa-release-manifest-metadata.v1",
        "sourceRef": str(metadata.get("sourceRef") or "").strip(),
        "sourceCommit": str(metadata.get("sourceCommit") or "").strip(),
        "builderId": builder_id,
        "artifacts": {},
    }
    for artifact in metadata.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        artifact_key = str(artifact.get("artifactKey") or "").strip()
        platform = str(artifact.get("platform") or "").strip()
        path = Path(str(artifact.get("path") or ""))
        sbom = artifact.get("sbom") if isinstance(artifact.get("sbom"), dict) else {}
        if not artifact_key or not platform:
            continue
        result["artifacts"].setdefault(artifact_key, {})[platform] = {
            "version": str(artifact.get("version") or "").strip(),
            "filename": path.name,
            "sha256": str(artifact.get("sha256") or "").strip(),
            "sizeBytes": int(artifact.get("sizeBytes") or 0),
            "lockSha256": str((artifact.get("lock") or {}).get("sha256") or "").strip()
            if isinstance(artifact.get("lock"), dict)
            else "",
            "sbomFilename": Path(str(sbom.get("path") or "")).name,
            "sbomSha256": str(sbom.get("sha256") or "").strip(),
            "downloadUrl": "",
            "sbomUrl": "",
            "provenanceUrl": "",
            "attestationUrl": "",
            "signatureUrl": "",
            "builderId": builder_id,
            "sourceRef": str(artifact.get("sourceRef") or metadata.get("sourceRef") or "").strip(),
            "sourceCommit": str(artifact.get("sourceCommit") or metadata.get("sourceCommit") or "").strip(),
        }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build H2OMeta release artifacts on Linux CI.")
    parser.add_argument("--platform", default="linux-64", choices=("linux-64", "linux-aarch64"))
    parser.add_argument("--source-ref", default=str(os.environ.get("GITHUB_SHA", "") or ""))
    parser.add_argument("--output-dir", default=str(Path("dist") / "remote-runner"))
    parser.add_argument("--metadata-name", default="release-artifacts-metadata.json")
    parser.add_argument("--manifest-metadata-name", default="release-manifest-metadata.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    source_ref = str(args.source_ref or "HEAD").strip()
    source_commit = ensure_source_ref_checked_out(source_ref)
    with tempfile.TemporaryDirectory(prefix="h2ometa-release-artifacts-") as raw_work_root:
        work_root = Path(raw_work_root)
        artifacts = [
            build_remote_runner_artifact(
                output_dir=output_dir,
                platform=args.platform,
                source_ref=source_ref,
                work_root=work_root,
                source_commit=source_commit,
            ),
            build_workflow_runtime_artifact(
                output_dir=output_dir,
                platform=args.platform,
                source_ref=source_ref,
                work_root=work_root,
                source_commit=source_commit,
            ),
        ]
    metadata = build_metadata(artifacts=artifacts, source_ref=source_ref, source_commit=source_commit)
    metadata_path = output_dir / args.metadata_name
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_release_attestations(metadata=metadata, output_dir=output_dir)
    manifest_metadata = release_manifest_metadata(metadata)
    manifest_metadata_path = output_dir / args.manifest_metadata_name
    manifest_metadata_path.write_text(json.dumps(manifest_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_json("RELEASE_ARTIFACTS_CI", metadata)
    print_json("RELEASE_MANIFEST_METADATA", manifest_metadata)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
