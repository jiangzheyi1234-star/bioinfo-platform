from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from core.execution.single_tool_result_parsers import parse_generic_result_table

if TYPE_CHECKING:
    from core.execution.tool_bridge_service import ToolBridgeService


class ToolBridgeArtifactHelper:
    """Artifact/manifest helpers extracted from ToolBridgeService."""

    def __init__(self, owner: ToolBridgeService) -> None:
        self._owner = owner

    def _get_current_project_dir(self) -> Path | None:
        pm = self._owner._get_project_manager()
        if pm is None:
            return None
        project_dir = getattr(pm, "current_project_dir", None)
        return Path(project_dir) if project_dir else None

    def _execution_results_dir(self, execution_id: str) -> Path | None:
        project_dir = self._get_current_project_dir()
        if project_dir is None or not execution_id:
            return None
        return project_dir / "results" / execution_id

    def _manifest_path(self, cache_key: str) -> Path | None:
        return self._owner._artifact_store.manifest_path(cache_key)

    def _load_manifest(self, cache_key: str) -> dict | None:
        return self._owner._artifact_store.load_manifest(cache_key)

    def _normalize_artifacts(self, artifacts: list[dict] | None) -> list[dict]:
        return self._owner._artifact_store.normalize_artifacts(artifacts)

    def _artifact_by_name(self, artifacts: list[dict], name: str) -> dict | None:
        return self._owner._artifact_store.artifact_by_name(artifacts, name)

    def _local_artifact_path(self, artifacts: list[dict], name: str) -> Path | None:
        artifact = self._artifact_by_name(artifacts, name)
        if artifact is None:
            return None
        local_path = str(artifact.get("local_path") or "").strip()
        if not local_path:
            return None
        path = Path(local_path)
        return path if path.exists() else None

    def _read_local_artifact_text(self, artifacts: list[dict], name: str) -> str:
        return self._owner._artifact_store.read_local_artifact_text(artifacts, name)

    def _count_local_artifact_lines(self, artifacts: list[dict], name: str) -> int | None:
        return self._owner._artifact_store.count_local_artifact_lines(artifacts, name)

    @staticmethod
    def _available_artifacts(artifacts: list[dict]) -> list[dict]:
        return [artifact for artifact in artifacts if artifact.get("available")]

    @staticmethod
    def _local_result_dir_for_execution(execution_id: str, artifacts: list[dict]) -> str:
        for artifact in artifacts:
            local_path = str(artifact.get("local_path") or "").strip()
            if not local_path:
                continue
            return str(Path(local_path).parent)
        return ""

    def _artifact_from_result_views(
        self,
        descriptor: dict[str, Any],
        artifacts: list[dict],
        *,
        sample_id: str = "",
        preferred_types: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        result_views = list(descriptor.get("result_views", []) or [])
        for view in result_views:
            if preferred_types and str(view.get("type") or "").strip() not in preferred_types:
                continue
            data_source = str(view.get("data_source") or "").strip().replace("{sample_id}", sample_id)
            if not data_source:
                continue
            artifact = self._artifact_by_name(artifacts, Path(data_source).name)
            if artifact and artifact.get("available"):
                return artifact
        return None

    @staticmethod
    def _first_available_artifact_with_suffix(artifacts: list[dict], suffixes: tuple[str, ...]) -> dict[str, Any] | None:
        normalized_suffixes = tuple(item.lower() for item in suffixes)
        for artifact in artifacts:
            if not artifact.get("available"):
                continue
            name = str(artifact.get("name") or "").lower()
            if name.endswith(normalized_suffixes):
                return artifact
        return None

    @staticmethod
    def _parse_table_file(path: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
        payload = parse_generic_result_table(path)
        return (
            list(payload.get("columns") or []),
            list(payload.get("rows") or []),
            dict(payload.get("metrics") or {}),
        )

    @staticmethod
    def _summarize_row_count(rows: list[dict[str, Any]], *, label: str) -> list[dict[str, str]]:
        return [{"label": label, "value": str(len(rows)), "tone": "primary"}]

    def _remote_cache_key(self, tool_id: str, remote_result_dir: str) -> str:
        return self._owner._artifact_store.remote_cache_key(tool_id, remote_result_dir)

    def _remote_file_exists(self, ssh: Any, remote_path: str) -> bool:
        return self._owner._artifact_store.remote_file_exists(ssh, remote_path)

    def _cache_remote_artifacts(self, tool_id: str, remote_result_dir: str) -> list[dict]:
        return self._owner._artifact_store.cache_remote_artifacts(
            tool_id=tool_id,
            remote_result_dir=remote_result_dir,
            result_artifact_names=self._owner._result_artifact_names,
            ssh=self._owner._get_ssh_service(),
        )

    def list_local_execution_artifacts(self, execution_id: str) -> list[dict]:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return []
        return self._owner._artifact_store.list_local_execution_artifacts(normalized_execution_id)

    def _persist_execution_artifacts(
        self,
        execution_id: str,
        tool_id: str,
        output_dir: str,
        artifacts: list[dict],
    ) -> list[dict]:
        return self._owner._artifact_store.persist_execution_artifacts(
            execution_id=execution_id,
            tool_id=tool_id,
            output_dir=output_dir,
            artifacts=artifacts,
        )

    def download_execution_artifacts(self, execution_id: str) -> list[dict]:
        return self.list_local_execution_artifacts(execution_id)

    @staticmethod
    def _format_execution_time(timestamp: Any) -> str:
        if timestamp in (None, ""):
            return ""
        try:
            return datetime.datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""

    @staticmethod
    def _parse_execution_parameters_strict(raw: Any, execution_id: str) -> dict[str, Any]:
        if raw in ("", None):
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        try:
            data = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"执行参数 JSON 解析失败: execution_id={execution_id}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"执行参数必须是对象: execution_id={execution_id}")
        return data

    def _build_parameter_items(self, raw_parameters: Any, execution_id: str) -> list[dict[str, str]]:
        params = self._parse_execution_parameters_strict(raw_parameters, execution_id)
        return [
            {"label": str(key), "value": str(value)}
            for key, value in params.items()
            if value not in ("", None)
        ]

    def _build_execution_result_context(
        self,
        execution_row: Any,
        artifacts: list[dict] | None = None,
    ) -> dict[str, Any]:
        execution_id = str(execution_row["execution_id"] or "")
        tool_id = str(execution_row["tool_id"] or "")
        artifacts = self._normalize_artifacts(artifacts or self.list_local_execution_artifacts(execution_id))
        if not artifacts:
            raise RuntimeError(
                f"执行结果缺少工件清单: tool={tool_id}, execution_id={execution_id}"
            )
        manifest = self._load_manifest(execution_id) or {}
        return {
            "execution_id": execution_id,
            "tool_id": tool_id,
            "sample_id": str(execution_row["sample_id"] or ""),
            "sample_name": str(execution_row["sample_name"] or execution_row["sample_id"] or ""),
            "updated_at": self._format_execution_time(execution_row["completed_at"] or execution_row["created_at"]),
            "tool_version": str(execution_row["tool_version"] or ""),
            "artifacts": artifacts,
            "remote_result_dir": str(manifest.get("output_dir") or "").strip(),
            "local_result_dir": self._local_result_dir_for_execution(execution_id, artifacts),
            "parameters": self._build_parameter_items(execution_row["parameters"], execution_id),
        }
