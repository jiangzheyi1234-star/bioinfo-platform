import os

# 默认配置字典
DEFAULT_CONFIG = {
    'ip': '192.168.0.152',
    'user': 'zyserver',
    'pwd': 'abc123..',
    'remote_dir': '/home/zyserver/project/lzc_project/blast_temp/',
    'remote_db': '/home/zyserver/project_ssd/common_data/core_nt_database/core_nt',
    'blast_bin': '/home/zyserver/anaconda3/envs/ncbi_download/bin/blastn',
    'local_file': '',  # 运行时指定
    'local_output_dir': r'C:\PathogenAnalyzer\output'
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

