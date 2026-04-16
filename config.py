"""配置管理 - 读写 config.json，SSH 密码安全存储。"""

import json
import os
import threading
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(os.getenv("APPDATA", "") or Path.home()) / "H2OMeta" / "config.json"
if os.name != "nt":
    _CONFIG_PATH = Path.home() / ".h2ometa" / "config.json"

_CACHE: dict | None = None
_LOCK = threading.RLock()


def default_config() -> dict:
    return {
        "ssh": {
            "host": "",
            "port": 22,
            "user": "",
            "password": "",
            "use_key": False,
            "key_file": "",
        },
        "linux": {"conda_executable": ""},
        "databases": {"db_root": ""},
    }


def get_config() -> dict:
    global _CACHE
    with _LOCK:
        if _CACHE:
            return dict(_CACHE)
        if not _CONFIG_PATH.exists():
            _CACHE = default_config()
            return dict(_CACHE)
        try:
            _CACHE = json.loads(_CONFIG_PATH.read_text())
        except Exception:
            _CACHE = default_config()
        return dict(_CACHE)


def save_config(cfg: dict) -> None:
    global _CACHE
    with _LOCK:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        _CACHE = cfg


def resolve_ssh_password(cfg: dict) -> str:
    ssh = cfg.get("ssh", {})
    pwd = ssh.get("password", "")
    if pwd:
        return pwd
    if ssh.get("use_key"):
        return ""
    ref = ssh.get("password_ref", "")
    if ref:
        try:
            import keyring

            return keyring.get_password("h2ometa.ssh", ref) or ""
        except Exception:
            return ""
    return ""
