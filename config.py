import json
import os
from pathlib import Path
from typing import Any

# 默认配置字典
DEFAULT_CONFIG = {
    'ip': '192.168.0.152',
    'user': 'zyserver',
    'pwd': 'abc123..',
    'ncbi_api_key': '',
    'remote_dir': '/home/zyserver/project/lzc_project/blast_temp/',
    'remote_db': '/home/zyserver/project_ssd/common_data/core_nt_database/core_nt',
    'blast_bin': '/home/zyserver/anaconda3/envs/ncbi_download/bin/blastn',
    'local_file': '',  # 运行时指定
    'local_output_dir': r'C:\PathogenAnalyzer\output',
    # 异步任务调度配置
    'poll_interval': 5,  # 状态轮询间隔（秒）
    'max_poll_retries': 3,  # 轮询失败最大重试次数
    'screen_check_timeout': 10,  # screen 命令超时时间（秒）
    # 远程脚本路径
    'remote_script': '/home/zyserver/project/lzc_project/project/h2oapp/blast_main.sh',
}

# 数据库映射
DB_MAP = {
    "Core nucleotide database (core_nt)": "/home/zyserver/project_ssd/common_data/core_nt_database/core_nt",
    "Custom (manual input)": ""
}

def ensure_output_dir(path):
    """确保输出目录存在"""
    if not os.path.exists(path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            # 回退到用户目录
            path = os.path.join(os.path.expanduser("~"), "PathogenAnalyzer", "output")
            os.makedirs(path, exist_ok=True)
    return path

# 初始化时确保默认目录存在
DEFAULT_CONFIG['local_output_dir'] = ensure_output_dir(DEFAULT_CONFIG['local_output_dir'])


# ── 配置文件读写 ────────────────────────────────────────────

_CONFIG_PATH = Path.home() / ".h2ometa" / "config.json"


def get_config() -> dict[str, Any]:
    """读取用户配置文件，合并默认值。

    配置文件路径: ~/.h2ometa/config.json
    不存在时返回 DEFAULT_CONFIG 的副本。
    """
    config = dict(DEFAULT_CONFIG)
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            config.update(user_config)
        except Exception:
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    """保存配置到用户配置文件。"""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
