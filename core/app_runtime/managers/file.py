from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.managers.base import BaseRuntimeManager


class FileManager(BaseRuntimeManager):
    def upload_file(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        return self.call_runner(
            "upload_content",
            preferred_server_id=body.get("serverId"),
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
        with self._service._lock:
            self._service._ensure_initialized()
            ssh = self._service._ensure_ssh_connected()
        data = ssh.list_directory(path, directories_only=directories_only, limit=limit, offset=offset)
        return {"data": data}
