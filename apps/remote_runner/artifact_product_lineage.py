from __future__ import annotations

from typing import Any


def input_artifacts_from_lineage(lineage_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_blob: dict[str, dict[str, Any]] = {}
    for edge in lineage_edges:
        if edge.get("predicate") != "prov:used" or edge.get("objectKind") != "artifact_blob":
            continue
        artifact_blob_id = str(edge.get("objectId") or "").strip()
        if not artifact_blob_id:
            continue
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        item = by_blob.setdefault(
            artifact_blob_id,
            {
                "artifactBlobId": artifact_blob_id,
                "sha256": str(payload.get("sha256") or edge.get("contentHash") or ""),
                "mimeType": str(payload.get("mimeType") or ""),
                "sizeBytes": _optional_int(payload.get("sizeBytes")),
                "ports": [],
            },
        )
        if not item.get("sha256") and (payload.get("sha256") or edge.get("contentHash")):
            item["sha256"] = str(payload.get("sha256") or edge.get("contentHash"))
        if not item.get("mimeType") and payload.get("mimeType"):
            item["mimeType"] = str(payload["mimeType"])
        if item.get("sizeBytes") is None and payload.get("sizeBytes") is not None:
            item["sizeBytes"] = _optional_int(payload.get("sizeBytes"))
        port = {
            "portName": str(payload.get("portName") or payload.get("inputRole") or ""),
            "inputName": str(payload.get("inputName") or ""),
            "inputRole": str(payload.get("inputRole") or "input"),
            "inputIndex": _optional_int(payload.get("inputIndex")),
            "filename": str(payload.get("filename") or ""),
            "uploadId": str(payload.get("uploadId") or ""),
            "runArtifactEdgeId": str(payload.get("runArtifactEdgeId") or ""),
            "lineageEdgeId": str(edge.get("lineageEdgeId") or ""),
        }
        if port not in item["ports"]:
            item["ports"].append(port)
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


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
