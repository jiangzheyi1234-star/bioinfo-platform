import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_VERSION = 2


def _resolve_config_path() -> Path:
    """统一配置文件路径。"""
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "H2OMeta" / "config.json"
    return Path.home() / ".h2ometa" / "config.json"


_CONFIG_PATH = _resolve_config_path()


def get_config_path() -> Path:
    return _CONFIG_PATH


def load_raw_config() -> Any:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def ensure_output_dir(path: str) -> str:
    """确保输出目录存在。"""
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            path = os.path.join(os.path.expanduser("~"), "PathogenAnalyzer", "output")
            os.makedirs(path, exist_ok=True)
    return path


def default_settings_schema() -> dict[str, Any]:
    """v2 统一配置模型。"""
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
            "conda_executable": "",      # 检测到的 conda 绝对路径
            "auto_installed": False,     # 是否 H2OMeta 自动安装的 Miniforge
            "conda_env_path": "",        # DEPRECATED, 保留兼容
            "conda_env_name": "",        # DEPRECATED, 保留兼容
        },
        "execution": {
            "max_concurrent": 3,
            "screen_check_timeout": 10,
        },
        "databases": {
            "kraken2": "",
            "checkm2": "",
            "gtdbtk": "",
            "blast_nt": "",
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
        },
    }


def _is_v2_schema(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and data.get("version") == CONFIG_VERSION
        and isinstance(data.get("ssh"), dict)
        and isinstance(data.get("linux"), dict)
        and isinstance(data.get("execution"), dict)
        and isinstance(data.get("databases"), dict)
        and isinstance(data.get("blast"), dict)
        and isinstance(data.get("ncbi"), dict)
        and isinstance(data.get("runtime"), dict)
    )


def migrate_legacy_config(data: dict[str, Any]) -> dict[str, Any]:
    """将旧扁平配置迁移到 v2 模型。仅供一次性迁移入口调用。"""
    schema = default_settings_schema()

    schema["ssh"]["host"] = str(data.get("server_ip") or data.get("ip") or schema["ssh"]["host"])
    port_val = data.get("ssh_port") or data.get("port") or schema["ssh"]["port"]
    try:
        schema["ssh"]["port"] = int(port_val)
    except (ValueError, TypeError):
        schema["ssh"]["port"] = 22
    schema["ssh"]["user"] = str(data.get("ssh_user") or data.get("user") or schema["ssh"]["user"])
    schema["ssh"]["password"] = str(data.get("ssh_pwd") or data.get("pwd") or schema["ssh"]["password"])

    schema["linux"]["conda_env_path"] = str(data.get("conda_env_path") or schema["linux"]["conda_env_path"])
    schema["linux"]["conda_env_name"] = str(data.get("conda_env_name") or schema["linux"]["conda_env_name"])

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
    """规范化为 v2 配置模型。非 v2 输入会回退默认值。"""
    if not _is_v2_schema(data):
        return default_settings_schema()

    defaults = default_settings_schema()
    schema = deepcopy(defaults)
    for section in ("ssh", "linux", "execution", "databases", "blast", "ncbi", "runtime"):
        section_data = data.get(section)
        if isinstance(section_data, dict):
            schema[section].update(section_data)

    schema["version"] = CONFIG_VERSION
    schema["runtime"]["local_output_dir"] = ensure_output_dir(
        str(schema["runtime"].get("local_output_dir") or "")
    )
    return schema


def get_config() -> dict[str, Any]:
    """读取并返回 v2 配置模型。旧 schema 不在运行期读取。"""
    try:
        raw = load_raw_config()
        return normalize_config(raw)
    except Exception:
        return default_settings_schema()


def save_config(config: dict[str, Any]) -> None:
    """保存 v2 配置。"""
    schema = normalize_config(config)
    schema["version"] = CONFIG_VERSION
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)


def get_runtime_setting(key: str, default: Any = None) -> Any:
    config = get_config()
    execution = config.get("execution", {})
    if key in execution:
        return execution.get(key, default)

    runtime = config.get("runtime", {})
    if key in runtime:
        return runtime.get(key, default)

    return default


def get_blast_setting(key: str, default: Any = None) -> Any:
    return get_config().get("blast", {}).get(key, default)


def get_database_path(key: str, default: str = "") -> str:
    config = get_config()
    databases = config.get("databases", {})
    if key == "blast_nt":
        fallback = str(config.get("blast", {}).get("db_path", default) or default)
        return str(databases.get(key) or fallback)
    return str(databases.get(key) or default)


def get_ncbi_setting(key: str, default: Any = None) -> Any:
    return get_config().get("ncbi", {}).get(key, default)


def sync_default_from_schema(schema: dict[str, Any]) -> None:
    """将 v2 模型同步到旧模块依赖的扁平 DEFAULT_CONFIG。"""
    normalized = normalize_config(schema)
    databases = normalized["databases"]
    execution = normalized["execution"]
    runtime = normalized["runtime"]
    blast = normalized["blast"]
    DEFAULT_CONFIG.update(
        {
            "ip": normalized["ssh"]["host"],
            "port": normalized["ssh"]["port"],
            "user": normalized["ssh"]["user"],
            "pwd": normalized["ssh"]["password"],
            "ncbi_api_key": normalized["ncbi"]["api_key"],
            "ncbi_email": normalized["ncbi"]["email"],
            "remote_dir": blast["remote_work_dir"],
            "remote_db": str(databases.get("blast_nt") or blast["db_path"]),
            "blast_bin": blast["bin_path"],
            "remote_script": blast["remote_script"],
            "local_file": runtime["local_file"],
            "local_output_dir": runtime["local_output_dir"],
            "max_concurrent": execution["max_concurrent"],
            "max_poll_retries": runtime["max_poll_retries"],
            "screen_check_timeout": execution["screen_check_timeout"],
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
    "max_concurrent": 3,
    "max_poll_retries": 3,
    "screen_check_timeout": 10,
}

sync_default_from_schema(get_config())



