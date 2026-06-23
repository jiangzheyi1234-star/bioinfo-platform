from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any


RESULT_PACKAGE_VALIDATION_SCHEMA_VERSION = "h2ometa.result-package-validation.v1"
DEFAULT_RESULT_PACKAGE_SCHEMA_VERSION = "h2ometa.result-package.v2"
DEFAULT_RESULT_PACKAGE_PROFILE = "h2ometa.result-evidence-package.v1"
RO_CRATE_CONTEXT_1_1 = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_SPEC_URI = "https://w3id.org/ro/crate/1.1"
WORKFLOW_RUN_CONTEXT = "https://w3id.org/ro/terms/workflow-run/context"
PROCESS_RUN_CRATE_PROFILE_URI = "https://w3id.org/ro/wfrun/process/0.5"
WORKFLOW_RUN_CRATE_PROFILE_URI = "https://w3id.org/ro/wfrun/workflow/0.5"
WORKFLOW_RO_CRATE_PROFILE_URI = "https://w3id.org/workflowhub/workflow-ro-crate/1.0"
REQUIRED_METADATA_FILES = {
    "metadata/artifact-audit.json",
    "metadata/evidence-events.json",
    "metadata/lineage.json",
    "metadata/rules.json",
    "metadata/run-events.json",
    "metadata/run.json",
    "metadata/workflow-revision.json",
}
REQUIRED_ROOT_PROFILE_URIS = {
    PROCESS_RUN_CRATE_PROFILE_URI,
    WORKFLOW_RUN_CRATE_PROFILE_URI,
    WORKFLOW_RO_CRATE_PROFILE_URI,
}


def validate_result_package_archive(
    package_path: Path,
    *,
    expected_manifest_sha256: str | None = None,
    expected_schema_version: str = DEFAULT_RESULT_PACKAGE_SCHEMA_VERSION,
    expected_package_profile: str = DEFAULT_RESULT_PACKAGE_PROFILE,
) -> dict[str, Any]:
    package_path = Path(package_path)
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    try:
        with zipfile.ZipFile(package_path) as archive:
            names = archive.namelist()
            name_set = set(names)
            _validate_zip_names(names, errors)
            manifest, manifest_raw = _read_json_entry(archive, "manifest.json", errors)
            ro_crate, _ = _read_json_entry(archive, "ro-crate-metadata.json", errors)
            if manifest is None or manifest_raw is None or ro_crate is None:
                _raise_validation_failed(errors)
            manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
            if expected_manifest_sha256 and manifest_sha256 != expected_manifest_sha256:
                errors.append("manifest.json sha256 does not match expected manifestSha256")
            _validate_manifest(
                archive=archive,
                names=name_set,
                manifest=manifest,
                expected_schema_version=expected_schema_version,
                expected_package_profile=expected_package_profile,
                errors=errors,
            )
            _validate_ro_crate(
                ro_crate=ro_crate,
                manifest=manifest,
                errors=errors,
            )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"RESULT_PACKAGE_VALIDATION_FAILED: invalid zip archive: {exc}") from exc

    _raise_validation_failed(errors)
    checks.append({"name": "zip-shape", "status": "passed", "entryCount": len(name_set)})
    checks.append({"name": "manifest", "status": "passed", "sha256": manifest_sha256})
    checks.append({"name": "metadata-files", "status": "passed"})
    checks.append({"name": "workflow-run-ro-crate", "status": "passed"})
    return {
        "schemaVersion": RESULT_PACKAGE_VALIDATION_SCHEMA_VERSION,
        "status": "passed",
        "checkedAt": _utc_now_iso(),
        "manifestSha256": manifest_sha256,
        "checks": checks,
    }


def _validate_zip_names(names: list[str], errors: list[str]) -> None:
    if len(names) != len(set(names)):
        errors.append("zip archive contains duplicate entries")
    for name in names:
        if not _is_safe_posix_path(name):
            errors.append(f"zip entry path is unsafe: {name}")


def _validate_manifest(
    *,
    archive: zipfile.ZipFile,
    names: set[str],
    manifest: dict[str, Any],
    expected_schema_version: str,
    expected_package_profile: str,
    errors: list[str],
) -> None:
    if manifest.get("schemaVersion") != expected_schema_version:
        errors.append("manifest schemaVersion is unsupported")
    if manifest.get("packageProfile") != expected_package_profile:
        errors.append("manifest packageProfile is unsupported")
    for key in ("resultId", "runId", "workflowRevisionId", "pipelineId", "createdAt"):
        if not str(manifest.get(key) or "").strip():
            errors.append(f"manifest {key} is required")

    run = manifest.get("run")
    workflow_revision = manifest.get("workflowRevision")
    if not isinstance(run, dict):
        errors.append("manifest run must be an object")
    elif run.get("workflowRevisionId") != manifest.get("workflowRevisionId"):
        errors.append("manifest run.workflowRevisionId must match workflowRevisionId")
    if not isinstance(workflow_revision, dict):
        errors.append("manifest workflowRevision must be an object")
    elif not str(workflow_revision.get("contentHash") or "").strip():
        errors.append("manifest workflowRevision.contentHash is required")

    include_artifacts = manifest.get("includeArtifacts")
    artifact_payload_mode = str(manifest.get("artifactPayloadMode") or "")
    if type(include_artifacts) is not bool:
        errors.append("manifest includeArtifacts must be boolean")
    elif include_artifacts and artifact_payload_mode != "included":
        errors.append("manifest artifactPayloadMode must be included")
    elif include_artifacts is False and artifact_payload_mode != "metadata-only":
        errors.append("manifest artifactPayloadMode must be metadata-only")

    _validate_metadata_files(
        archive=archive,
        names=names,
        metadata_files=manifest.get("metadataFiles"),
        errors=errors,
    )
    _validate_manifest_artifacts(
        archive=archive,
        names=names,
        artifacts=manifest.get("artifacts"),
        artifact_count=manifest.get("artifactCount"),
        include_artifacts=include_artifacts,
        errors=errors,
    )


def _validate_metadata_files(
    *,
    archive: zipfile.ZipFile,
    names: set[str],
    metadata_files: Any,
    errors: list[str],
) -> None:
    if not isinstance(metadata_files, list):
        errors.append("manifest metadataFiles must be a list")
        return
    paths: list[str] = []
    for item in metadata_files:
        if not isinstance(item, dict):
            errors.append("manifest metadataFiles entries must be objects")
            continue
        path = str(item.get("path") or "")
        paths.append(path)
        if path not in REQUIRED_METADATA_FILES:
            errors.append(f"manifest metadata file is not part of the package profile: {path}")
        if not path.startswith("metadata/") or not path.endswith(".json") or not _is_safe_posix_path(path):
            errors.append(f"manifest metadata file path is unsafe: {path}")
        if path not in names:
            errors.append(f"manifest metadata file is missing from archive: {path}")
            continue
        raw = archive.read(path)
        size_bytes = _int_value(item.get("sizeBytes"))
        if size_bytes != len(raw):
            errors.append(f"manifest metadata file sizeBytes mismatch: {path}")
        if str(item.get("sha256") or "") != hashlib.sha256(raw).hexdigest():
            errors.append(f"manifest metadata file sha256 mismatch: {path}")
    if set(paths) != REQUIRED_METADATA_FILES:
        errors.append("manifest metadataFiles must exactly match the result evidence package profile")
    if len(paths) != len(set(paths)):
        errors.append("manifest metadataFiles contains duplicate paths")


def _validate_manifest_artifacts(
    *,
    archive: zipfile.ZipFile,
    names: set[str],
    artifacts: Any,
    artifact_count: Any,
    include_artifacts: bool | Any,
    errors: list[str],
) -> None:
    if not isinstance(artifacts, list):
        errors.append("manifest artifacts must be a list")
        return
    if _int_value(artifact_count) != len(artifacts):
        errors.append("manifest artifactCount must match artifacts length")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("manifest artifact entries must be objects")
            continue
        artifact_id = str(artifact.get("artifactId") or "")
        sha256 = str(artifact.get("sha256") or "")
        if not artifact_id:
            errors.append("manifest artifactId is required")
        if len(sha256) != 64:
            errors.append(f"manifest artifact sha256 is invalid: {artifact_id}")
        if artifact.get("includedInPackage") is not include_artifacts:
            errors.append(f"manifest artifact includedInPackage mismatch: {artifact_id}")
        package_path = artifact.get("packagePath")
        if include_artifacts:
            _validate_included_artifact_payload(
                archive=archive,
                names=names,
                artifact=artifact,
                package_path=package_path,
                errors=errors,
            )
        else:
            if package_path is not None:
                errors.append(f"metadata-only artifact packagePath must be null: {artifact_id}")
            if not str(artifact.get("externalUri") or "").strip():
                errors.append(f"metadata-only artifact externalUri is required: {artifact_id}")
            if any(name.startswith(f"artifacts/{artifact_id}/") for name in names):
                errors.append(f"metadata-only archive contains artifact payload: {artifact_id}")


def _validate_included_artifact_payload(
    *,
    archive: zipfile.ZipFile,
    names: set[str],
    artifact: dict[str, Any],
    package_path: Any,
    errors: list[str],
) -> None:
    artifact_id = str(artifact.get("artifactId") or "")
    root = str(package_path or "")
    if not root or not _is_safe_posix_path(root):
        errors.append(f"included artifact packagePath is unsafe: {artifact_id}")
        return
    prefix = f"{root.rstrip('/')}/"
    payload_names = sorted(name for name in names if name.startswith(prefix) and not name.endswith("/"))
    if not payload_names:
        errors.append(f"included artifact payload is missing: {artifact_id}")
        return
    size_bytes, sha256 = _archive_payload_stats(archive, payload_names, prefix)
    if _int_value(artifact.get("sizeBytes")) != size_bytes:
        errors.append(f"included artifact sizeBytes mismatch: {artifact_id}")
    if str(artifact.get("sha256") or "") != sha256:
        errors.append(f"included artifact sha256 mismatch: {artifact_id}")


def _archive_payload_stats(
    archive: zipfile.ZipFile,
    payload_names: list[str],
    prefix: str,
) -> tuple[int, str]:
    relative_files = [(name.removeprefix(prefix), name) for name in payload_names]
    directories: set[str] = set()
    for relative, _name in relative_files:
        parent = PurePosixPath(relative).parent
        while parent.as_posix() not in {"", "."}:
            directories.add(parent.as_posix())
            parent = parent.parent
    if len(relative_files) == 1 and not directories:
        raw = archive.read(relative_files[0][1])
        return len(raw), hashlib.sha256(raw).hexdigest()

    digest = hashlib.sha256()
    size_bytes = 0
    entries: list[tuple[str, str, str | None]] = [
        (directory, "directory", None) for directory in directories
    ]
    entries.extend((relative, "file", name) for relative, name in relative_files)
    for relative, entry_type, name in sorted(entries, key=lambda item: item[0]):
        if entry_type == "directory":
            digest.update(f"D\t{relative}\0".encode("utf-8"))
            continue
        digest.update(f"F\t{relative}\0".encode("utf-8"))
        raw = archive.read(str(name))
        size_bytes += len(raw)
        digest.update(raw)
    return size_bytes, digest.hexdigest()


def _validate_ro_crate(
    *,
    ro_crate: dict[str, Any],
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    context_ids = _id_values(ro_crate.get("@context"))
    if RO_CRATE_CONTEXT_1_1 not in context_ids:
        errors.append("RO-Crate context must include RO-Crate 1.1")
    if WORKFLOW_RUN_CONTEXT not in context_ids:
        errors.append("RO-Crate context must include workflow-run terms")
    graph = ro_crate.get("@graph")
    if not isinstance(graph, list):
        errors.append("RO-Crate @graph must be a list")
        return
    graph_by_id = _graph_by_id(graph, errors)
    descriptor = graph_by_id.get("ro-crate-metadata.json")
    root = graph_by_id.get("./")
    if descriptor is None:
        errors.append("RO-Crate metadata descriptor is missing")
    else:
        _validate_ro_crate_descriptor(descriptor, errors)
    if root is None:
        errors.append("RO-Crate root dataset is missing")
        return
    _validate_ro_crate_root(root, graph_by_id, manifest, errors)


def _validate_ro_crate_descriptor(descriptor: dict[str, Any], errors: list[str]) -> None:
    if not _type_contains(descriptor.get("@type"), "CreativeWork"):
        errors.append("RO-Crate metadata descriptor must be CreativeWork")
    if _first_id(descriptor.get("about")) != "./":
        errors.append("RO-Crate metadata descriptor must reference the root dataset")
    if RO_CRATE_SPEC_URI not in _id_values(descriptor.get("conformsTo")):
        errors.append("RO-Crate metadata descriptor must conform to RO-Crate 1.1")


def _validate_ro_crate_root(
    root: dict[str, Any],
    graph_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    if not _type_contains(root.get("@type"), "Dataset"):
        errors.append("RO-Crate root entity must be Dataset")
    root_profiles = _id_values(root.get("conformsTo"))
    missing_profiles = sorted(REQUIRED_ROOT_PROFILE_URIS - root_profiles)
    if missing_profiles:
        errors.append(f"RO-Crate root dataset missing profile conformsTo: {', '.join(missing_profiles)}")

    metadata_files = manifest.get("metadataFiles")
    artifacts = manifest.get("artifacts")
    metadata_paths = (
        {str(item.get("path") or "") for item in metadata_files if isinstance(item, dict)}
        if isinstance(metadata_files, list)
        else set()
    )
    artifact_ids = (
        {_artifact_ro_crate_id(artifact) for artifact in artifacts if isinstance(artifact, dict)}
        if isinstance(artifacts, list)
        else set()
    )
    expected_parts = {"manifest.json", *metadata_paths, *artifact_ids}
    has_part_ids = _id_values(root.get("hasPart"))
    missing_parts = sorted(expected_parts - has_part_ids)
    if missing_parts:
        errors.append(f"RO-Crate root hasPart is missing package entries: {', '.join(missing_parts)}")

    workflow_id = _first_id(root.get("mainEntity"))
    if not workflow_id:
        errors.append("RO-Crate root mainEntity is required")
    workflow = graph_by_id.get(workflow_id)
    if workflow is None:
        errors.append("RO-Crate ComputationalWorkflow entity is missing")
    else:
        _validate_workflow_entity(workflow, manifest, errors)

    run_action_id = _first_id(root.get("mentions"))
    run_action = graph_by_id.get(run_action_id)
    if run_action is None:
        errors.append("RO-Crate workflow run CreateAction is missing")
    else:
        _validate_run_action(run_action, workflow_id, artifact_ids, errors)

    _validate_ro_crate_artifact_entities(graph_by_id, manifest, errors)


def _validate_workflow_entity(
    workflow: dict[str, Any],
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    if not _type_contains(workflow.get("@type"), "ComputationalWorkflow"):
        errors.append("RO-Crate workflow entity must be ComputationalWorkflow")
    if not _type_contains(workflow.get("@type"), "SoftwareSourceCode"):
        errors.append("RO-Crate workflow entity must be SoftwareSourceCode")
    workflow_revision = manifest.get("workflowRevision") or {}
    if workflow.get("identifier") != manifest.get("workflowRevisionId"):
        errors.append("RO-Crate workflow identifier must match workflowRevisionId")
    if workflow.get("sha256") != workflow_revision.get("contentHash"):
        errors.append("RO-Crate workflow sha256 must match workflowRevision.contentHash")


def _validate_run_action(
    run_action: dict[str, Any],
    workflow_id: str,
    artifact_ids: set[str],
    errors: list[str],
) -> None:
    if not _type_contains(run_action.get("@type"), "CreateAction"):
        errors.append("RO-Crate workflow run entity must be CreateAction")
    if _first_id(run_action.get("instrument")) != workflow_id:
        errors.append("RO-Crate workflow run instrument must reference main workflow")
    result_ids = _id_values(run_action.get("result"))
    missing_results = sorted(artifact_ids - result_ids)
    if missing_results:
        errors.append(f"RO-Crate workflow run result is missing artifacts: {', '.join(missing_results)}")


def _validate_ro_crate_artifact_entities(
    graph_by_id: dict[str, dict[str, Any]],
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = _artifact_ro_crate_id(artifact)
        entity = graph_by_id.get(artifact_id)
        if entity is None:
            errors.append(f"RO-Crate artifact entity is missing: {artifact_id}")
            continue
        if entity.get("identifier") != artifact.get("artifactId"):
            errors.append(f"RO-Crate artifact identifier mismatch: {artifact_id}")
        if entity.get("contentSize") != artifact.get("sizeBytes"):
            errors.append(f"RO-Crate artifact contentSize mismatch: {artifact_id}")
        if entity.get("sha256") != artifact.get("sha256"):
            errors.append(f"RO-Crate artifact sha256 mismatch: {artifact_id}")
        if entity.get("h2ometa:includedInPackage") is not artifact.get("includedInPackage"):
            errors.append(f"RO-Crate artifact includedInPackage mismatch: {artifact_id}")


def _read_json_entry(
    archive: zipfile.ZipFile,
    name: str,
    errors: list[str],
) -> tuple[dict[str, Any] | None, bytes | None]:
    try:
        raw = archive.read(name)
    except KeyError:
        errors.append(f"required archive entry is missing: {name}")
        return None, None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"archive entry is not valid JSON: {name}: {exc}")
        return None, raw
    if not isinstance(payload, dict):
        errors.append(f"archive JSON entry must be an object: {name}")
        return None, raw
    return payload, raw


def _graph_by_id(graph: list[Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in graph:
        if not isinstance(item, dict):
            errors.append("RO-Crate @graph entries must be objects")
            continue
        entity_id = str(item.get("@id") or "")
        if not entity_id:
            errors.append("RO-Crate @graph entry is missing @id")
            continue
        if entity_id in result:
            errors.append(f"RO-Crate @graph contains duplicate @id: {entity_id}")
            continue
        result[entity_id] = item
    return result


def _artifact_ro_crate_id(artifact: dict[str, Any]) -> str:
    if artifact.get("includedInPackage"):
        return f"{artifact.get('packagePath') or ''}/"
    return str(artifact.get("externalUri") or "")


def _id_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return {str(value.get("@id") or "")} - {""}
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_id_values(item))
        return result
    return set()


def _first_id(value: Any) -> str:
    ids = sorted(_id_values(value))
    return ids[0] if ids else ""


def _type_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return expected in {str(item) for item in value}
    return False


def _is_safe_posix_path(path: str) -> bool:
    if not path or "\\" in path:
        return False
    parsed = PurePosixPath(path)
    return not parsed.is_absolute() and all(part not in {"", ".", ".."} for part in parsed.parts)


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _raise_validation_failed(errors: list[str]) -> None:
    if errors:
        raise ValueError(f"RESULT_PACKAGE_VALIDATION_FAILED: {'; '.join(errors)}")


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
