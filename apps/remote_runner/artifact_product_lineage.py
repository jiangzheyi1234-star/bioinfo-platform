from __future__ import annotations

from typing import Any


def input_artifacts_from_lineage(lineage_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_blob: dict[str, dict[str, Any]] = {}
    for edge in lineage_edges:
        if edge.get("predicate") != "prov:used" or edge.get("objectKind") != "artifact_blob":
            continue
        artifact_blob_id = _required_text(
            edge.get("objectId"),
            "RESULT_PACKAGE_INPUT_ARTIFACT_BLOB_REQUIRED",
        )
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        item = by_blob.setdefault(
            artifact_blob_id,
            {
                "artifactBlobId": artifact_blob_id,
                "ports": [],
            },
        )
        if "sha256" in payload:
            _set_once_or_match(
                item,
                key="sha256",
                value=_required_sha256(payload.get("sha256"), artifact_blob_id),
                conflict_code="RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_CONFLICT",
            )
        if "mimeType" in payload:
            _set_once_or_match(
                item,
                key="mimeType",
                value=_required_text(
                    payload.get("mimeType"),
                    "RESULT_PACKAGE_INPUT_ARTIFACT_MIME_TYPE_REQUIRED",
                    artifact_blob_id=artifact_blob_id,
                ),
                conflict_code="RESULT_PACKAGE_INPUT_ARTIFACT_MIME_TYPE_CONFLICT",
            )
        if "sizeBytes" in payload:
            _set_once_or_match(
                item,
                key="sizeBytes",
                value=_required_nonnegative_int(payload.get("sizeBytes"), artifact_blob_id),
                conflict_code="RESULT_PACKAGE_INPUT_ARTIFACT_SIZE_BYTES_CONFLICT",
            )
        port = {
            "portName": str(payload.get("portName") or payload.get("inputRole") or ""),
            "inputName": str(payload.get("inputName") or ""),
            "inputRole": str(payload.get("inputRole") or "input"),
            "inputIndex": _optional_port_index(payload.get("inputIndex"), artifact_blob_id),
            "sourceType": str(payload.get("sourceType") or ""),
            "sourceId": str(payload.get("sourceId") or ""),
            "filename": str(payload.get("filename") or ""),
            "uploadId": str(payload.get("uploadId") or ""),
            "artifactId": str(payload.get("artifactId") or ""),
            "sourceMaterializationId": str(payload.get("sourceMaterializationId") or ""),
            "sourceStorageBackend": str(payload.get("sourceStorageBackend") or ""),
            "upstreamRunId": str(payload.get("upstreamRunId") or ""),
            "runArtifactEdgeId": str(payload.get("runArtifactEdgeId") or ""),
            "lineageEdgeId": str(edge.get("lineageEdgeId") or ""),
        }
        if port not in item["ports"]:
            item["ports"].append(port)
    _validate_input_artifacts(by_blob.values())
    return sorted(
        by_blob.values(),
        key=lambda item: (
            _first_input_index(item.get("ports") or []),
            str(item.get("artifactBlobId") or ""),
        ),
    )


def input_artifact_ro_crate_id(artifact: dict[str, Any]) -> str:
    return f"urn:h2ometa:artifact-blob:{artifact['artifactBlobId']}"


def input_artifact_name(artifact: dict[str, Any]) -> str:
    ports = artifact.get("ports") if isinstance(artifact.get("ports"), list) else []
    for port in ports:
        if not isinstance(port, dict):
            continue
        name = str(port.get("portName") or port.get("filename") or "").strip()
        if name:
            return name
    return str(artifact.get("artifactBlobId") or "input artifact")


def _first_input_index(ports: list[Any]) -> int:
    indexes = [
        int(port["inputIndex"])
        for port in ports
        if isinstance(port, dict) and isinstance(port.get("inputIndex"), int)
    ]
    return min(indexes) if indexes else 0


def _validate_input_artifacts(artifacts: Any) -> None:
    for artifact in artifacts:
        artifact_blob_id = artifact["artifactBlobId"]
        _required_sha256(artifact.get("sha256"), artifact_blob_id)
        _required_text(
            artifact.get("mimeType"),
            "RESULT_PACKAGE_INPUT_ARTIFACT_MIME_TYPE_REQUIRED",
            artifact_blob_id=artifact_blob_id,
        )
        _required_nonnegative_int(artifact.get("sizeBytes"), artifact_blob_id)


def _set_once_or_match(
    item: dict[str, Any],
    *,
    key: str,
    value: object,
    conflict_code: str,
) -> None:
    current = item.get(key)
    if current is None:
        item[key] = value
        return
    if current != value:
        raise ValueError(f"{conflict_code}: {item['artifactBlobId']}")


def _required_text(
    value: object,
    code: str,
    *,
    artifact_blob_id: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_lineage_error(code, artifact_blob_id))
    return value.strip()


def _required_sha256(value: object, artifact_blob_id: str) -> str:
    sha256 = _required_text(
        value,
        "RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_REQUIRED",
        artifact_blob_id=artifact_blob_id,
    ).lower()
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError(_lineage_error("RESULT_PACKAGE_INPUT_ARTIFACT_SHA256_INVALID", artifact_blob_id))
    return sha256


def _required_nonnegative_int(value: object, artifact_blob_id: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(_lineage_error("RESULT_PACKAGE_INPUT_ARTIFACT_SIZE_BYTES_REQUIRED", artifact_blob_id))
    return value


def _optional_port_index(value: object, artifact_blob_id: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise ValueError(_lineage_error("RESULT_PACKAGE_INPUT_ARTIFACT_PORT_INDEX_INVALID", artifact_blob_id))
    return value


def _lineage_error(code: str, artifact_blob_id: str | None) -> str:
    if artifact_blob_id:
        return f"{code}: {artifact_blob_id}"
    return code
