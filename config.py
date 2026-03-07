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
            "host": "192.168.0.152",
            "user": "zyserver",
            "password": "abc123..",
        },
        "linux": {
            "project_root": "",
            "conda_env_path": "",
            "conda_env_name": "",
        },
        "blast": {
            "db_path": "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt",
            "bin_path": "/home/zyserver/anaconda3/envs/ncbi_download/bin/blastn",
            "remote_work_dir": "/home/zyserver/project/lzc_project/blast_temp/",
            "remote_script": "/home/zyserver/project/lzc_project/project/h2oapp/blast_main.sh",
        },
        "ncbi": {
            "api_key": "",
        },
        "runtime": {
            "local_file": "",
            "local_output_dir": ensure_output_dir(r"C:\PathogenAnalyzer\output"),
            "poll_interval": 5,
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
        and isinstance(data.get("blast"), dict)
        and isinstance(data.get("ncbi"), dict)
        and isinstance(data.get("runtime"), dict)
    )


def migrate_legacy_config(data: dict[str, Any]) -> dict[str, Any]:
    """将旧扁平配置迁移到 v2 模型。仅供一次性迁移入口调用。"""
    schema = default_settings_schema()

    schema["ssh"]["host"] = str(data.get("server_ip") or data.get("ip") or schema["ssh"]["host"])
    schema["ssh"]["user"] = str(data.get("ssh_user") or data.get("user") or schema["ssh"]["user"])
    schema["ssh"]["password"] = str(data.get("ssh_pwd") or data.get("pwd") or schema["ssh"]["password"])

    schema["linux"]["project_root"] = str(data.get("linux_project_path") or schema["linux"]["project_root"])
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
    if "poll_interval" in data:
        runtime["poll_interval"] = int(data.get("poll_interval") or runtime["poll_interval"])
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
    for section in ("ssh", "linux", "blast", "ncbi", "runtime"):
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


def sync_default_from_schema(schema: dict[str, Any]) -> None:
    """将 v2 模型同步到旧模块依赖的扁平 DEFAULT_CONFIG。"""
    normalized = normalize_config(schema)
    DEFAULT_CONFIG.update(
        {
            "ip": normalized["ssh"]["host"],
            "user": normalized["ssh"]["user"],
            "pwd": normalized["ssh"]["password"],
            "ncbi_api_key": normalized["ncbi"]["api_key"],
            "remote_dir": normalized["blast"]["remote_work_dir"],
            "remote_db": normalized["blast"]["db_path"],
            "blast_bin": normalized["blast"]["bin_path"],
            "remote_script": normalized["blast"]["remote_script"],
            "local_file": normalized["runtime"]["local_file"],
            "local_output_dir": normalized["runtime"]["local_output_dir"],
            "poll_interval": normalized["runtime"]["poll_interval"],
            "max_poll_retries": normalized["runtime"]["max_poll_retries"],
            "screen_check_timeout": normalized["runtime"]["screen_check_timeout"],
        }
    )


# 旧代码仍引用 DEFAULT_CONFIG，这里保证其值来自统一 v2 配置模型
DEFAULT_CONFIG = {
    "ip": "",
    "user": "",
    "pwd": "",
    "ncbi_api_key": "",
    "remote_dir": "",
    "remote_db": "",
    "blast_bin": "",
    "remote_script": "",
    "local_file": "",
    "local_output_dir": "",
    "poll_interval": 5,
    "max_poll_retries": 3,
    "screen_check_timeout": 10,
}

DB_MAP = {
    "Core nucleotide database (core_nt)": "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt",
    "Custom (manual input)": "",
}

sync_default_from_schema(get_config())
