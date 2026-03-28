import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_VERSION = 2


def _resolve_config_path() -> Path:
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "H2OMeta" / "config.json"
    return Path.home() / ".h2ometa" / "config.json"


_CONFIG_PATH = _resolve_config_path()
_CONFIG_CACHE_LOCK = threading.RLock()
_CONFIG_CACHE: dict[str, Any] | None = None
_CONFIG_CACHE_FINGERPRINT: tuple[int, int] | None = None
_DEFAULT_CONFIG_LOCK = threading.RLock()


def get_config_path() -> Path:
    return _CONFIG_PATH


def _get_config_fingerprint() -> tuple[int, int] | None:
    try:
        stat = _CONFIG_PATH.stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def load_raw_config() -> Any:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def ensure_output_dir(path: str) -> str:
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            path = os.path.join(os.path.expanduser("~"), "PathogenAnalyzer", "output")
            os.makedirs(path, exist_ok=True)
    return path


def default_settings_schema() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "ssh": {
            "host": "",
            "port": 22,
            "user": "",
            "password": "",
            "use_key": False,
            "key_file": "",
        },
        "linux": {
            "conda_executable": "",
        },
        "databases": {
            "db_root": "",
            "overrides": {},
        },
        "blast": {
            "db_path": "",
            "bin_path": "",
            "remote_work_dir": "",
            "remote_script": "",
        },
        "ncbi": {
            "api_key": "",
            "email": "",
        },
        "runtime": {
            "local_file": "",
            "local_output_dir": ensure_output_dir(r"C:\PathogenAnalyzer\output"),
            "max_poll_retries": 3,
            "screen_check_timeout": 10,
            "primer_result_root": "",
            "db_connect_timeout_sec": 20,
            "db_busy_timeout_ms": 20000,
            "db_journal_mode": "delete",
        },
    }


def _is_v2_schema(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("version") == CONFIG_VERSION
        and isinstance(data.get("ssh"), dict)
        and isinstance(data.get("linux"), dict)
        and isinstance(data.get("databases"), dict)
        and isinstance(data.get("blast"), dict)
        and isinstance(data.get("ncbi"), dict)
        and isinstance(data.get("runtime"), dict)
    )


def migrate_legacy_config(data: dict[str, Any]) -> dict[str, Any]:
    schema = default_settings_schema()

    schema["ssh"]["host"] = str(data.get("server_ip") or data.get("ip") or schema["ssh"]["host"])
    port_val = data.get("ssh_port") or data.get("port") or schema["ssh"]["port"]
    try:
        schema["ssh"]["port"] = int(port_val)
    except (ValueError, TypeError):
        schema["ssh"]["port"] = 22
    schema["ssh"]["user"] = str(data.get("ssh_user") or data.get("user") or schema["ssh"]["user"])
    schema["ssh"]["password"] = str(data.get("ssh_pwd") or data.get("pwd") or schema["ssh"]["password"])

    schema["blast"]["db_path"] = str(data.get("remote_db") or schema["blast"]["db_path"])
    schema["blast"]["bin_path"] = str(data.get("blast_bin") or schema["blast"]["bin_path"])
    schema["blast"]["remote_work_dir"] = str(data.get("remote_dir") or schema["blast"]["remote_work_dir"])
    schema["blast"]["remote_script"] = str(data.get("remote_script") or schema["blast"]["remote_script"])

    schema["ncbi"]["api_key"] = str(data.get("ncbi_api_key") or schema["ncbi"]["api_key"])

    runtime = schema["runtime"]
    if "local_file" in data:
        runtime["local_file"] = str(data.get("local_file") or "")
    if "local_output_dir" in data:
        runtime["local_output_dir"] = ensure_output_dir(str(data.get("local_output_dir") or runtime["local_output_dir"]))
    if "max_poll_retries" in data:
        runtime["max_poll_retries"] = int(data.get("max_poll_retries") or runtime["max_poll_retries"])
    if "screen_check_timeout" in data:
        runtime["screen_check_timeout"] = int(data.get("screen_check_timeout") or runtime["screen_check_timeout"])

    return schema


def normalize_config(data: Any) -> dict[str, Any]:
    if not _is_v2_schema(data):
        return default_settings_schema()

    defaults = default_settings_schema()
    schema = deepcopy(defaults)
    for section in ("ssh", "linux", "databases", "blast", "ncbi", "runtime"):
        section_data = data.get(section)
        if isinstance(section_data, dict):
            if section == "databases":
                old_keys = {k for k in section_data if k not in ("db_root", "overrides")}
                if old_keys:
                    overrides = {
                        str(k): str(v)
                        for k, v in section_data.items()
                        if k not in ("db_root", "overrides") and str(v or "").strip()
                    }
                    schema["databases"] = {
                        "db_root": str(section_data.get("db_root", "") or ""),
                        "overrides": overrides,
                    }
                else:
                    schema["databases"]["db_root"] = str(section_data.get("db_root", "") or "")
                    overrides = section_data.get("overrides", {})
                    if isinstance(overrides, dict):
                        schema["databases"]["overrides"] = {
                            str(k): str(v)
                            for k, v in overrides.items()
                            if str(v or "").strip()
                        }
            else:
                for key in defaults[section].keys():
                    if key in section_data:
                        schema[section][key] = section_data[key]

    schema["version"] = CONFIG_VERSION
    schema["linux"]["conda_executable"] = str(schema["linux"].get("conda_executable") or "")
    schema["runtime"]["local_output_dir"] = ensure_output_dir(str(schema["runtime"].get("local_output_dir") or ""))
    return schema


def get_config() -> dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_CACHE_FINGERPRINT
    try:
        fingerprint = _get_config_fingerprint()
        with _CONFIG_CACHE_LOCK:
            if _CONFIG_CACHE is not None and _CONFIG_CACHE_FINGERPRINT == fingerprint:
                return deepcopy(_CONFIG_CACHE)

        raw = load_raw_config()
        normalized = normalize_config(raw)

        with _CONFIG_CACHE_LOCK:
            _CONFIG_CACHE = normalized
            _CONFIG_CACHE_FINGERPRINT = fingerprint
            return deepcopy(_CONFIG_CACHE)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError, ValueError, TypeError):
        return default_settings_schema()


def save_config(config: dict[str, Any]) -> None:
    global _CONFIG_CACHE, _CONFIG_CACHE_FINGERPRINT
    schema = normalize_config(config)
    schema["version"] = CONFIG_VERSION
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE = deepcopy(schema)
        _CONFIG_CACHE_FINGERPRINT = _get_config_fingerprint()


def get_runtime_setting(key: str, default: Any = None) -> Any:
    config = get_config()
    runtime = config.get("runtime", {})
    return runtime.get(key, default)


def get_blast_setting(key: str, default: Any = None) -> Any:
    return get_config().get("blast", {}).get(key, default)


def get_database_path(key: str, default: str = "") -> str:
    config = get_config()
    databases = config.get("databases", {})
    overrides = databases.get("overrides", {})
    if isinstance(overrides, dict):
        override_value = str(overrides.get(key, "") or "").strip()
        if override_value:
            return override_value
    db_root = str(databases.get("db_root", "") or "").strip()
    if db_root:
        return db_root
    return str(default or "")


def get_ncbi_setting(key: str, default: Any = None) -> Any:
    return get_config().get("ncbi", {}).get(key, default)


def sync_default_from_schema(schema: dict[str, Any]) -> None:
    normalized = normalize_config(schema)
    databases = normalized["databases"]
    overrides = databases.get("overrides", {}) if isinstance(databases, dict) else {}
    runtime = normalized["runtime"]
    blast = normalized["blast"]
    with _DEFAULT_CONFIG_LOCK:
        DEFAULT_CONFIG.update(
            {
                "ip": normalized["ssh"]["host"],
                "port": normalized["ssh"]["port"],
                "user": normalized["ssh"]["user"],
                "pwd": normalized["ssh"]["password"],
                "ncbi_api_key": normalized["ncbi"]["api_key"],
                "ncbi_email": normalized["ncbi"]["email"],
                "remote_dir": blast["remote_work_dir"],
                "remote_db": str((overrides.get("blast_nt") if isinstance(overrides, dict) else "") or blast["db_path"]),
                "blast_bin": blast["bin_path"],
                "remote_script": blast["remote_script"],
                "local_file": runtime["local_file"],
                "local_output_dir": runtime["local_output_dir"],
                "max_poll_retries": runtime["max_poll_retries"],
                "screen_check_timeout": runtime["screen_check_timeout"],
            }
        )


DEFAULT_CONFIG = {
    "ip": "",
    "user": "",
    "pwd": "",
    "ncbi_api_key": "",
    "ncbi_email": "",
    "remote_dir": "",
    "remote_db": "",
    "blast_bin": "",
    "remote_script": "",
    "local_file": "",
    "local_output_dir": "",
    "max_poll_retries": 3,
    "screen_check_timeout": 10,
}

sync_default_from_schema(get_config())
