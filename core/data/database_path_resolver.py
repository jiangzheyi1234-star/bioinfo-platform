from __future__ import annotations

import logging
import shlex
from typing import Callable

from core.data.database_service import DatabaseService

logger = logging.getLogger(__name__)

SshRunFn = Callable[[str, int], tuple[int, str, str]]


class DatabasePathResolver:
    """Resolve database paths with a strict modern config policy.

    Resolution order:
      1) overrides[db_id]
      2) db_root + databases.yaml install_path
    """

    def __init__(self, db_cfg: dict, ssh_run_fn: SshRunFn | None = None):
        cfg = db_cfg if isinstance(db_cfg, dict) else {}
        overrides = cfg.get("overrides", {})
        self._overrides = overrides if isinstance(overrides, dict) else {}
        self._db_root = str(cfg.get("db_root", "") or "").strip()
        self._ssh_run_fn = ssh_run_fn
        self._expanded_cache: dict[str, str] = {}

    def resolve(self, db_id: str, param_name: str, db_service: DatabaseService) -> str | None:
        key_id = str(db_id or "").strip()
        key_param = str(param_name or "").strip()

        override_raw = str(self._overrides.get(key_id, "") or "").strip()
        if override_raw:
            resolved = self._expand(override_raw)
            logger.debug("数据库路径已匹配(override): id=%s → %s=%s", key_id, key_param, resolved)
            return resolved

        if self._db_root and key_id:
            combined = db_service.get_resolved_path(key_id, self._db_root)
            if combined:
                resolved = self._expand(combined)
                logger.debug("数据库路径已匹配(db_root): id=%s → %s=%s", key_id, key_param, resolved)
                return resolved

        logger.debug("数据库路径未匹配: id=%s, param=%s", key_id, key_param)
        return None

    def _expand(self, path: str) -> str:
        raw = str(path or "").strip()
        if not raw or not raw.startswith("~"):
            return raw
        cached = self._expanded_cache.get(raw)
        if cached is not None:
            return cached

        expanded = raw
        if self._ssh_run_fn is not None:
            cmd = f"eval echo {shlex.quote(raw)}"
            try:
                rc, out, _ = self._ssh_run_fn(cmd, 10)
                if rc == 0 and out.strip():
                    expanded = out.strip()
            except Exception:
                logger.debug("展开数据库路径失败，保留原值: %s", raw, exc_info=True)

        self._expanded_cache[raw] = expanded
        return expanded
