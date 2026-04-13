import json
import os
import threading
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any

CONFIG_VERSION = 2
_SSH_KEYRING_SERVICE = "h2ometa.ssh"


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
            "password_ref": "",
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


def _assert_v2_schema(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    if not data:
        raise ValueError("config file is empty; expected v2 schema")
    if not _is_v2_schema(data):
        raise ValueError("legacy config format is no longer supported; expected v2 schema")
    _assert_structured_databases_schema(data.get("databases"))
    return data


def _assert_structured_databases_schema(section: Any) -> None:
    if not isinstance(section, dict):
        raise ValueError("legacy config format is no longer supported; expected v2 schema")
    allowed_keys = {"db_root", "overrides"}
    unknown_keys = sorted(str(key) for key in section.keys() if key not in allowed_keys)
    if unknown_keys:
        raise ValueError("legacy config format is no longer supported; expected v2 schema")
    overrides = section.get("overrides")
    if overrides is not None and not isinstance(overrides, dict):
        raise ValueError("legacy config format is no longer supported; expected v2 schema")


def normalize_config(data: Any) -> dict[str, Any]:
    validated = _assert_v2_schema(data)

    defaults = default_settings_schema()
    schema = deepcopy(defaults)
    for section in ("ssh", "linux", "databases", "blast", "ncbi", "runtime"):
        section_data = validated.get(section)
        if isinstance(section_data, dict):
            for key in defaults[section].keys():
                if key in section_data:
                    schema[section][key] = section_data[key]

    overrides = validated["databases"].get("overrides", {})
    if isinstance(overrides, dict):
        schema["databases"]["overrides"] = {
            str(k): str(v)
            for k, v in overrides.items()
            if str(v or "").strip()
        }

    schema["version"] = CONFIG_VERSION
    schema["linux"]["conda_executable"] = str(schema["linux"].get("conda_executable") or "")
    schema["runtime"]["local_output_dir"] = ensure_output_dir(str(schema["runtime"].get("local_output_dir") or ""))
    schema["ssh"]["password"] = str(schema["ssh"].get("password") or "")
    schema["ssh"]["password_ref"] = str(schema["ssh"].get("password_ref") or "")
    return schema


def _load_keyring_backend() -> Any:
    try:
        return import_module("keyring")
    except ModuleNotFoundError as exc:
        raise RuntimeError("keyring is required for SSH password storage") from exc


def _ssh_secret_ref(ssh_section: dict[str, Any]) -> str:
    host = str(ssh_section.get("host", "") or "").strip()
    user = str(ssh_section.get("user", "") or "").strip()
    port = int(ssh_section.get("port", 22) or 22)
    if not host or not user:
        raise RuntimeError("ssh.host and ssh.user are required before saving SSH password")
    return f"ssh://{user}@{host}:{port}"


def _store_ssh_password(password_ref: str, password: str) -> None:
    keyring = _load_keyring_backend()
    keyring.set_password(_SSH_KEYRING_SERVICE, password_ref, password)


def _read_ssh_password(password_ref: str) -> str:
    if not password_ref:
        return ""
    keyring = _load_keyring_backend()
    value = keyring.get_password(_SSH_KEYRING_SERVICE, password_ref)
    if value is None:
        raise RuntimeError(f"SSH password is missing from keyring: {password_ref}")
    return str(value)


def _delete_ssh_password(password_ref: str) -> None:
    if not password_ref:
        return
    keyring = _load_keyring_backend()
    try:
        keyring.delete_password(_SSH_KEYRING_SERVICE, password_ref)
    except Exception:
        pass


def resolve_ssh_password(config_or_ssh_section: dict[str, Any]) -> str:
    ssh_section = config_or_ssh_section.get("ssh", config_or_ssh_section)
    if not isinstance(ssh_section, dict):
        return ""
    password = str(ssh_section.get("password", "") or "")
    if password:
        return password
    password_ref = str(ssh_section.get("password_ref", "") or "").strip()
    if not password_ref or bool(ssh_section.get("use_key", False)):
        return ""
    return _read_ssh_password(password_ref)


def _secure_ssh_section_for_persist(ssh_section: dict[str, Any]) -> None:
    if bool(ssh_section.get("use_key", False)):
        existing_ref = str(ssh_section.get("password_ref", "") or "").strip()
        if existing_ref:
            _delete_ssh_password(existing_ref)
        ssh_section["password"] = ""
        ssh_section["password_ref"] = ""
        return

    plaintext = str(ssh_section.get("password", "") or "")
    existing_ref = str(ssh_section.get("password_ref", "") or "").strip()
    if plaintext:
        password_ref = _ssh_secret_ref(ssh_section)
        _store_ssh_password(password_ref, plaintext)
        ssh_section["password_ref"] = password_ref
        ssh_section["password"] = ""
        return

    if existing_ref:
        _read_ssh_password(existing_ref)
        ssh_section["password"] = ""
        return

    ssh_section["password"] = ""
    ssh_section["password_ref"] = ""


def _write_config(schema: dict[str, Any]) -> None:
    global _CONFIG_CACHE, _CONFIG_CACHE_FINGERPRINT
    schema["version"] = CONFIG_VERSION
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE = deepcopy(schema)
        _CONFIG_CACHE_FINGERPRINT = _get_config_fingerprint()


def get_config() -> dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_CACHE_FINGERPRINT
    fingerprint = _get_config_fingerprint()
    if fingerprint is None:
        return default_settings_schema()

    with _CONFIG_CACHE_LOCK:
        if _CONFIG_CACHE is not None and _CONFIG_CACHE_FINGERPRINT == fingerprint:
            return deepcopy(_CONFIG_CACHE)

    raw = load_raw_config()
    normalized = normalize_config(raw)
    ssh_section = normalized.get("ssh", {})
    if isinstance(ssh_section, dict) and str(ssh_section.get("password", "") or "").strip():
        migrated = deepcopy(normalized)
        _secure_ssh_section_for_persist(migrated["ssh"])
        _write_config(migrated)
        normalized = migrated

    with _CONFIG_CACHE_LOCK:
        _CONFIG_CACHE = normalized
        _CONFIG_CACHE_FINGERPRINT = _get_config_fingerprint()
        return deepcopy(_CONFIG_CACHE)


def save_config(config: dict[str, Any]) -> None:
    schema = normalize_config(config)
    _secure_ssh_section_for_persist(schema["ssh"])
    _write_config(schema)


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
