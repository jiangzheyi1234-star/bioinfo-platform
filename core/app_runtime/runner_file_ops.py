from __future__ import annotations

from typing import Any, Optional


class RunnerFileOperationsMixin:
    def upload_file(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        return self._call_remote_runner(
            manager.upload_content,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            filename=str(body.get("filename") or ""),
            content_base64=str(body.get("contentBase64") or ""),
            mime_type=str(body.get("mimeType") or "application/octet-stream"),
        )

    def list_remote_files(
        self,
        path: str = "",
        *,
        directories_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
        data = ssh.list_directory(path, directories_only=directories_only, limit=limit, offset=offset)
        return {"data": data}
