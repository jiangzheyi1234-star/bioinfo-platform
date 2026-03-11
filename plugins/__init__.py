"""H2OMeta 插件系统 - YAML 声明式工具管理

插件按 category 组织，每个工具由 tool.yaml 描述。
"""

# 插件系统由 core.plugin_registry 负责加载和管理
# 此文件仅作为包标识符，保持目录结构一致性

__all__ = [
    "analysis_paths.yaml",  # 3 条分析路径定义
    "databases.yaml",       # 数据库列表
]
