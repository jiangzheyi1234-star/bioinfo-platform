from __future__ import annotations

from typing import Any, Optional


class RunnerFileOperationsMixin:
    def upload_file(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.files.upload_file(payload)

    def list_remote_files(
        self,
        path: str = "",
        *,
        directories_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.files.list_remote_files(
            path,
            directories_only=directories_only,
            limit=limit,
            offset=offset,
        )
