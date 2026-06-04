from __future__ import annotations

import json
import time
from typing import Any

from .tool_contract import normalize_contract_status


def status_detail_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def set_status(
    status: dict[str, dict[str, str]],
    key: str,
    result: str,
    code: str,
    message: str,
    *,
    run_id: str = "",
    log_path: str = "",
    details: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    item = {
        "status": result,
        "message": message,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if code:
        item["code"] = code
    if run_id:
        item["runId"] = run_id
    if log_path:
        item["logPath"] = log_path
    if details:
        item.update({key: str(value) for key, value in details.items() if str(value)})
    status[key] = item
    return normalize_contract_status(status)


def validation_result(*, status: dict[str, dict[str, str]], ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "contractStatus": status, "message": message}
