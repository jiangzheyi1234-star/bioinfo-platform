"""配置管理 - 读写 config.json，SSH 密码安全存储。"""

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import keyring
import paramiko

SSH_KEYRING_SERVICE = "H2OMeta.SSH"
RUNNER_KEYRING_SERVICE = "H2OMeta.Runner"
SSH_AUTH_MODES = {"password_ref", "key_file", "ssh_config", "agent"}
_NATIVE_PATH_CLS = type(Path.cwd())


def _native_path(raw: str) -> Path:
    return _NATIVE_PATH_CLS(raw)


def get_app_data_dir() -> Path:
    if os.name == "nt":
        appdata = str(os.getenv("APPDATA", "") or "").strip()
        if appdata:
            return _native_path(appdata) / "H2OMeta"
        return _native_path(str(Path.home())) / "AppData" / "Roaming" / "H2OMeta"
    return _native_path(str(Path.home())) / ".h2ometa"


def get_app_cache_dir() -> Path:
    if os.name == "nt":
        localappdata = str(os.getenv("LOCALAPPDATA", "") or "").strip()
        if localappdata:
            return _native_path(localappdata) / "H2OMeta" / "Cache"
        return _native_path(str(Path.home())) / "AppData" / "Local" / "H2OMeta" / "Cache"

    xdg_cache_home = str(os.getenv("XDG_CACHE_HOME", "") or "").strip()
    if xdg_cache_home:
        return _native_path(xdg_cache_home) / "h2ometa"
    return _native_path(str(Path.home())) / ".cache" / "h2ometa"


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
            "auth_mode": "password_ref",
            "ssh_host_alias": "",
            "password_ref": "",
            "identity_ref": "",
            "remember_auth": True,
            "host": "",
            "port": 22,
            "user": "",
            "timeout_sec": 5,
            "auto_connect_on_startup": False,
        },
        "linux": {"conda_executable": ""},
        "databases": {"db_root": ""},
        "servers": {},
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


def normalize_ssh_config(ssh_cfg: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(ssh_cfg or {})
    auth_mode = str(raw.get("auth_mode", "") or "").strip()
    ssh_host_alias = str(raw.get("ssh_host_alias", "") or "").strip()
    identity_ref = str(raw.get("identity_ref", "") or "").strip()
    password_ref = str(raw.get("password_ref", "") or "").strip()

    if auth_mode not in SSH_AUTH_MODES:
        auth_mode = "password_ref"

    if auth_mode == "key_file":
        ssh_host_alias = ""
        password_ref = ""
    elif auth_mode == "ssh_config":
        password_ref = ""
    elif auth_mode == "agent":
        identity_ref = ""
        ssh_host_alias = ""
        password_ref = ""
    else:
        identity_ref = ""
        ssh_host_alias = ""

    return {
        "auth_mode": auth_mode,
        "ssh_host_alias": ssh_host_alias,
        "password_ref": password_ref,
        "identity_ref": identity_ref,
        "remember_auth": bool(raw.get("remember_auth", True)),
        "host": str(raw.get("host", "") or "").strip(),
        "port": int(raw.get("port", 22) or 22),
        "user": str(raw.get("user", "") or "").strip(),
        "timeout_sec": int(raw.get("timeout_sec", 5) or 5),
        "auto_connect_on_startup": bool(raw.get("auto_connect_on_startup", False)),
    }

def make_ssh_password_ref(host: str, port: int, user: str) -> str:
    return f"ssh://{user}@{host}:{port}"


def make_runner_token_ref(server_id: str) -> str:
    return f"runner://{server_id}"


def store_ssh_password(*, host: str, port: int, user: str, password: str) -> str:
    password_ref = make_ssh_password_ref(host=host, port=port, user=user)
    keyring.set_password(SSH_KEYRING_SERVICE, password_ref, password)
    return password_ref


def store_runner_token(*, server_id: str, token: str) -> str:
    token_ref = make_runner_token_ref(server_id)
    keyring.set_password(RUNNER_KEYRING_SERVICE, token_ref, token)
    return token_ref


def delete_ssh_password(password_ref: str) -> None:
    if not password_ref:
        return
    try:
        keyring.delete_password(SSH_KEYRING_SERVICE, password_ref)
    except keyring.errors.PasswordDeleteError:
        return
    except keyring.errors.KeyringError:
        raise
    except Exception:
        return


def delete_runner_token(token_ref: str) -> None:
    if not token_ref:
        return
    try:
        keyring.delete_password(RUNNER_KEYRING_SERVICE, token_ref)
    except keyring.errors.PasswordDeleteError:
        return
    except keyring.errors.KeyringError:
        raise
    except Exception:
        return


def resolve_ssh_password(cfg: dict) -> str:
    ssh = normalize_ssh_config(cfg.get("ssh", {}))
    password_ref = str(ssh.get("password_ref", "") or "").strip()
    if not password_ref:
        return ""
    password = keyring.get_password(SSH_KEYRING_SERVICE, password_ref)
    return str(password or "")


def resolve_runner_token(token_ref: str) -> str:
    if not token_ref:
        return ""
    token = keyring.get_password(RUNNER_KEYRING_SERVICE, token_ref)
    return str(token or "")


def get_default_ssh_config_path() -> Path:
    return Path.home() / ".ssh" / "config"


def resolve_ssh_config_target(ssh_cfg: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_ssh_config(ssh_cfg)
    alias = str(normalized.get("ssh_host_alias", "") or normalized.get("host", "") or "").strip()
    if not alias:
        raise ValueError("ssh_host_alias required for ssh_config auth mode")

    config_path = get_default_ssh_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"ssh config not found: {config_path}")

    parser = paramiko.SSHConfig()
    with config_path.open("r", encoding="utf-8") as handle:
        parser.parse(handle)
    resolved = parser.lookup(alias)
    host = str(resolved.get("hostname", alias) or alias).strip()
    user = str(normalized.get("user", "") or resolved.get("user", "") or "").strip()
    port = int(str(resolved.get("port", normalized.get("port", 22)) or 22))
    identity_value = resolved.get("identityfile", []) or []
    identity_ref = normalized.get("identity_ref", "")
    if not identity_ref and identity_value:
        if isinstance(identity_value, list):
            identity_ref = str(identity_value[0] or "").strip()
        else:
            identity_ref = str(identity_value).strip()
    return {
        **normalized,
        "host": host,
        "user": user,
        "port": port,
        "identity_ref": str(identity_ref or "").strip(),
    }
