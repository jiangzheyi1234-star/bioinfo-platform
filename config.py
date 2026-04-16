"""配置管理 - 读写 config.json，SSH 密码安全存储。"""

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

def get_app_data_dir() -> Path:
    if os.name == "nt":
        appdata = str(os.getenv("APPDATA", "") or "").strip()
        if appdata:
            return Path(appdata) / "H2OMeta"
        return Path.home() / "AppData" / "Roaming" / "H2OMeta"
    return Path.home() / ".h2ometa"


def get_ssh_key_dir() -> Path:
    return get_app_data_dir() / "ssh"


def resolve_ssh_keygen_executable() -> str:
    candidate = shutil.which("ssh-keygen")
    if candidate:
        return candidate
    if os.name == "nt":
        fallback = Path("C:/Windows/System32/OpenSSH/ssh-keygen.exe")
        if fallback.exists():
            return str(fallback)
    raise FileNotFoundError("ssh-keygen not found in PATH")


_CONFIG_PATH = get_app_data_dir() / "config.json"

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
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
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
    pwd = str(ssh.get("password", "") or "")
    if pwd:
        return pwd
    return ""
