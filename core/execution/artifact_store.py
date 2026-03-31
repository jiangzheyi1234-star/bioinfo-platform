"""Artifact cache and manifest persistence helpers for execution results."""

from __future__ import annotations

import hashlib
import json
import logging
import shlex
import shutil
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ArtifactStore:
    _ARTIFACT_TYPES = {"html", "json", "tsv", "text", "fasta", "archive", "binary"}
    _DISPLAY_ROLES = {"primary_result", "supporting_result", "download", "report", "provenance"}
    _VIEWER_HINTS = {"html", "table", "text", "json", "download"}

    def __init__(self, project_dir_getter: Callable[[], Path | None], manifest_name: str = "artifacts_manifest.json"):
        self._project_dir_getter = project_dir_getter
        self._manifest_name = manifest_name

    def execution_results_dir(self, execution_id: str) -> Path | None:
        project_dir = self._project_dir_getter()
        if project_dir is None or not execution_id:
            return None
        return project_dir / "results" / execution_id

    def manifest_path(self, cache_key: str) -> Path | None:
        project_dir = self._project_dir_getter()
        if project_dir is None or not cache_key:
            return None
        return project_dir / "results" / cache_key / self._manifest_name

    def load_manifest(self, cache_key: str) -> dict | None:
        manifest_path = self.manifest_path(cache_key)
        if manifest_path is None or not manifest_path.exists():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception:
            logger.exception("读取结果文件清单失败: %s", manifest_path)
            return None

    @staticmethod
    def normalize_artifacts(artifacts: list[dict] | None) -> list[dict]:
        normalized: list[dict] = []
        for item in artifacts or []:
            if not isinstance(item, dict):
                continue
            local_path = str(item.get("local_path") or "").strip()
            available = bool(item.get("available"))
            if local_path:
                available = Path(local_path).exists()
            normalized.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "remote_path": str(item.get("remote_path") or "").strip(),
                    "local_path": local_path,
                    "available": available,
                    "error": str(item.get("error") or "").strip(),
                    **ArtifactStore._normalize_artifact_metadata(item),
                }
            )
        return normalized

    @classmethod
    def infer_artifact_metadata(cls, artifact_name: str) -> dict[str, str]:
        name = str(artifact_name or "").strip()
        lower_name = name.lower()
        suffixes = Path(lower_name).suffixes
        suffix = suffixes[-1] if suffixes else ""

        artifact_type = "binary"
        viewer_hint = "download"
        display_role = "download"

        if suffix == ".html":
            artifact_type = "html"
            viewer_hint = "html"
            display_role = "report" if "report" in lower_name else "primary_result"
        elif suffix == ".json":
            artifact_type = "json"
            viewer_hint = "json"
            display_role = "supporting_result"
        elif suffix in {".tsv", ".csv"}:
            artifact_type = "tsv"
            viewer_hint = "table"
            display_role = "primary_result" if any(token in lower_name for token in ("result", "summary", "table")) else "supporting_result"
        elif suffix in {".txt", ".log"}:
            artifact_type = "text"
            viewer_hint = "text"
            display_role = "primary_result" if "result" in lower_name else "supporting_result"
        elif suffix in {".fa", ".fna", ".faa", ".fasta", ".fas"}:
            artifact_type = "fasta"
            viewer_hint = "download"
            display_role = "download"
        elif suffix in {".zip", ".tar", ".gz", ".bz2", ".xz"}:
            artifact_type = "archive"
            viewer_hint = "download"
            display_role = "download"

        if any(token in lower_name for token in ("provenance", "manifest", "metadata")):
            display_role = "provenance"
            viewer_hint = "json" if artifact_type == "json" else viewer_hint

        return {
            "artifact_type": artifact_type,
            "display_role": display_role,
            "viewer_hint": viewer_hint,
        }

    @classmethod
    def _normalize_artifact_metadata(cls, item: dict[str, Any]) -> dict[str, str]:
        inferred = cls.infer_artifact_metadata(str(item.get("name") or ""))
        artifact_type = str(item.get("artifact_type") or inferred["artifact_type"]).strip()
        display_role = str(item.get("display_role") or inferred["display_role"]).strip()
        viewer_hint = str(item.get("viewer_hint") or inferred["viewer_hint"]).strip()

        if artifact_type not in cls._ARTIFACT_TYPES:
            raise RuntimeError(f"Invalid artifact_type for artifact={item.get('name') or ''}: {artifact_type}")
        if display_role not in cls._DISPLAY_ROLES:
            raise RuntimeError(f"Invalid display_role for artifact={item.get('name') or ''}: {display_role}")
        if viewer_hint not in cls._VIEWER_HINTS:
            raise RuntimeError(f"Invalid viewer_hint for artifact={item.get('name') or ''}: {viewer_hint}")

        return {
            "artifact_type": artifact_type,
            "display_role": display_role,
            "viewer_hint": viewer_hint,
        }

    @staticmethod
    def artifact_by_name(artifacts: list[dict], name: str) -> dict | None:
        for artifact in artifacts:
            if artifact.get("name") == name:
                return artifact
        return None

    @classmethod
    def read_local_artifact_text(cls, artifacts: list[dict], name: str) -> str:
        artifact = cls.artifact_by_name(artifacts, name)
        if artifact is None:
            return ""
        local_path = str(artifact.get("local_path") or "").strip()
        if not local_path:
            return ""
        path = Path(local_path)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            logger.exception("读取本地结果文件失败: %s", local_path)
            return ""

    @classmethod
    def count_local_artifact_lines(cls, artifacts: list[dict], name: str) -> int | None:
        content = cls.read_local_artifact_text(artifacts, name)
        if not content:
            return None
        return len([line for line in content.splitlines() if line.strip()])

    @staticmethod
    def remote_cache_key(tool_id: str, remote_result_dir: str) -> str:
        digest = hashlib.sha1(remote_result_dir.encode("utf-8")).hexdigest()[:12]
        return f"{tool_id}_{digest}"

    @staticmethod
    def remote_file_exists(ssh: Any, remote_path: str) -> bool:
        quoted_path = shlex.quote(str(remote_path or ""))
        if not quoted_path:
            return False
        try:
            rc, _, _ = ssh.run(f"test -f {quoted_path}", timeout=10)
            return rc == 0
        except Exception:
            logger.debug("检查远端结果文件是否存在失败: %s", remote_path, exc_info=True)
            return False

    def cache_remote_artifacts(
        self,
        *,
        tool_id: str,
        remote_result_dir: str,
        result_artifact_names: dict[str, list[str]],
        ssh: Any,
    ) -> list[dict]:
        normalized_dir = (remote_result_dir or "").strip().rstrip("/")
        if not normalized_dir:
            return []

        cache_key = self.remote_cache_key(tool_id, normalized_dir)
        manifest = self.load_manifest(cache_key)
        if manifest:
            return self.normalize_artifacts(manifest.get("artifacts"))

        manifest_path = self.manifest_path(cache_key)
        if ssh is None or not getattr(ssh, "is_connected", False) or manifest_path is None:
            return []

        results_dir = manifest_path.parent
        results_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[dict] = []
        for name in result_artifact_names.get(tool_id, []):
            remote_path = f"{normalized_dir}/{name}"
            local_path = results_dir / name
            available = False
            error = ""
            try:
                if self.remote_file_exists(ssh, remote_path):
                    ssh.download(remote_path, str(local_path))
                    available = local_path.exists()
                else:
                    error = "remote_file_not_found"
                    logger.debug("远端结果文件不存在，跳过缓存: %s", remote_path)
            except Exception as exc:
                error = str(exc)
                logger.warning("缓存远端结果文件失败: %s (%s)", remote_path, exc)
            item = {
                "name": name,
                "remote_path": remote_path,
                "local_path": str(local_path),
                "available": available,
            }
            if error:
                item["error"] = error
            artifacts.append(item)

        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "execution_id": cache_key,
                        "tool_id": tool_id,
                        "output_dir": normalized_dir,
                        "artifacts": artifacts,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("写入远端结果缓存清单失败: %s", manifest_path)
        return self.normalize_artifacts(artifacts)

    def list_local_execution_artifacts(self, execution_id: str) -> list[dict]:
        manifest = self.load_manifest(str(execution_id or "").strip())
        if manifest:
            return self.normalize_artifacts(manifest.get("artifacts"))
        return []

    def persist_execution_artifacts(
        self,
        *,
        execution_id: str,
        tool_id: str,
        output_dir: str,
        artifacts: list[dict],
    ) -> list[dict]:
        normalized_execution_id = str(execution_id or "").strip()
        if not normalized_execution_id:
            return self.normalize_artifacts(artifacts)

        results_dir = self.execution_results_dir(normalized_execution_id)
        if results_dir is None:
            return self.normalize_artifacts(artifacts)
        results_dir.mkdir(parents=True, exist_ok=True)

        persisted: list[dict] = []
        for item in self.normalize_artifacts(artifacts):
            name = str(item.get("name") or "").strip()
            local_path = str(item.get("local_path") or "").strip()
            available = bool(item.get("available"))
            copied_path = ""
            error = str(item.get("error") or "").strip()
            metadata = self._normalize_artifact_metadata(item)
            if name and local_path and available and Path(local_path).exists():
                src = Path(local_path)
                dst = results_dir / name
                try:
                    if src.resolve() != dst.resolve():
                        shutil.copy2(src, dst)
                    copied_path = str(dst)
                except Exception as exc:
                    logger.warning("Failed to copy artifact to execution dir: %s -> %s (%s)", src, dst, exc)
                    error = error or str(exc)
                    copied_path = local_path
            else:
                copied_path = local_path

            persisted_item = {
                "name": name,
                "remote_path": str(item.get("remote_path") or "").strip(),
                "local_path": copied_path,
                "available": bool(copied_path) and Path(copied_path).exists(),
                **metadata,
            }
            if error:
                persisted_item["error"] = error
            persisted.append(persisted_item)

        manifest_path = results_dir / self._manifest_name
        try:
            manifest_path.write_text(
                json.dumps(
                    {
                        "execution_id": normalized_execution_id,
                        "tool_id": tool_id,
                        "output_dir": output_dir,
                        "artifacts": persisted,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to write execution artifacts manifest: %s", manifest_path)

        return self.normalize_artifacts(persisted)
