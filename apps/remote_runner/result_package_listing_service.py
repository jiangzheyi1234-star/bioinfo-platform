from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .result_package_download_service import result_package_download_url
from .result_package_storage import list_result_package_exports as list_result_package_export_records


RESULT_PACKAGE_EXPORT_LIST_SCHEMA_VERSION = "h2ometa.result-package-export-list.v1"


def list_result_package_exports(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    lifecycle_state: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    items = list_result_package_export_records(
        cfg,
        result_id=result_id,
        lifecycle_state=lifecycle_state,
        limit=limit,
    )
    return {
        "schemaVersion": RESULT_PACKAGE_EXPORT_LIST_SCHEMA_VERSION,
        "resultId": str(result_id or "").strip(),
        "lifecycleState": str(lifecycle_state or "").strip() or "all",
        "items": [_public_result_package_export(item) for item in items],
    }


def _public_result_package_export(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    public["evidenceId"] = public.pop("evidenceEventId", "")
    if public.get("lifecycleState") == "active":
        public["download"] = {
            "href": result_package_download_url(public["resultId"], public["packageExportId"]),
            "filename": _result_package_filename(public),
        }
    else:
        public.pop("download", None)
    public.pop("packagePath", None)
    public.pop("packageUri", None)
    return public


def _result_package_filename(item: dict[str, Any]) -> str:
    filename = Path(str(item.get("packagePath") or "")).name
    return filename or f"{item['packageExportId']}.zip"
