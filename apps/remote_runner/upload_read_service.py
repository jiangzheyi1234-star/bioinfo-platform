from __future__ import annotations

from typing import Any

from .route_utils import authorized_config, data_response, run_sync
from .upload_service import require_materialized_upload


async def get_upload_from_request(
    upload_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = await run_sync(authorized_config, authorization)
    upload = await run_sync(require_materialized_upload, cfg, upload_id)
    return data_response(upload)
