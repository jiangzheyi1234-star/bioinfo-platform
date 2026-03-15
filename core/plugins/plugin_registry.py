# core/plugin_registry.py
"""插件注册表 — 管理所有工具描述符的三层懒加载系统。

三层懒加载策略:
  Layer 1 (scan): 启动时扫描所有 tool.yaml，仅读取 id/name/category，构建索引
  Layer 2 (descriptor): 用户点击工具时，加载完整 YAML 描述符
  Layer 3 (full): 运行时解析模板、校验参数（由 CommandBuilder 负责）
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# Layer 1 索引中保留的头部字段
_HEADER_KEYS = ("id", "name", "category", "version", "description")


class PluginNotFoundError(KeyError):
    """请求的插件 ID 不存在于注册表中。"""


class PluginRegistry:
    """插件注册表 — 扫描 plugins/ 目录并提供三层懒加载访问。

    典型用法::

        registry = PluginRegistry(Path("plugins"))
        registry.scan()
        ids = registry.list_all_ids()
        desc = registry.get_descriptor("fastp")
    """

    def __init__(self, plugins_dir: Path | str) -> None:
        self._plugins_dir = Path(plugins_dir)
        # Layer 1: {tool_id: {name, category, version, description, path}}
        self._index: Dict[str, Dict[str, Any]] = {}
        # Layer 2: {tool_id: 完整 YAML dict}（按需加载）
        self._descriptors: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Layer 1 — 扫描
    # ------------------------------------------------------------------

    def scan(self) -> int:
        """扫描 plugins_dir 下所有 tool.yaml，构建索引。

        Returns:
            成功扫描的插件数量。
        """
        self._index.clear()
        self._descriptors.clear()

        if not self._plugins_dir.is_dir():
            logger.warning("插件目录不存在: %s", self._plugins_dir)
            return 0

        count = 0
        for yaml_path in sorted(self._plugins_dir.rglob("tool.yaml")):
            try:
                header = self._read_header(yaml_path)
                tool_id = header["id"]
                if tool_id in self._index:
                    logger.warning(
                        "插件 ID 冲突: %s (已注册: %s, 跳过: %s)",
                        tool_id,
                        self._index[tool_id]["path"],
                        yaml_path,
                    )
                    continue
                self._index[tool_id] = {
                    "name": header.get("name", tool_id),
                    "category": header.get("category", "unknown"),
                    "version": header.get("version", ""),
                    "description": header.get("description", ""),
                    "path": str(yaml_path),
                }
                count += 1
                logger.debug("已注册插件: %s (%s)", tool_id, yaml_path)
            except Exception:
                logger.exception("扫描插件失败: %s", yaml_path)

        logger.info("插件扫描完成: 共 %d 个插件", count)
        return count

    # ------------------------------------------------------------------
    # Layer 2 — 完整描述符
    # ------------------------------------------------------------------

    def get_descriptor(self, tool_id: str) -> Dict[str, Any]:
        """获取工具的完整 YAML 描述符（懒加载）。

        Args:
            tool_id: 工具唯一标识。

        Returns:
            完整的 YAML 字典。

        Raises:
            PluginNotFoundError: tool_id 不在索引中。
        """
        if tool_id not in self._index:
            raise PluginNotFoundError(f"未找到插件: {tool_id}")

        if tool_id not in self._descriptors:
            yaml_path = self._index[tool_id]["path"]
            try:
                with open(yaml_path, "r", encoding="utf-8") as fh:
                    self._descriptors[tool_id] = yaml.safe_load(fh)
                self._descriptors[tool_id]["_yaml_path"] = str(yaml_path)
                logger.debug("已加载描述符: %s", tool_id)
            except Exception:
                logger.exception("加载插件描述符失败: %s (%s)", tool_id, yaml_path)
                raise

        return self._descriptors[tool_id]

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def list_all_ids(self) -> List[str]:
        """返回所有已注册的工具 ID 列表。"""
        return list(self._index.keys())

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        """按分类过滤，返回匹配的索引条目列表。

        每个条目包含: id, name, category, version, description, path。
        """
        return [
            {"id": tool_id, **entry}
            for tool_id, entry in self._index.items()
            if entry["category"] == category
        ]

    def get_index_entry(self, tool_id: str) -> Dict[str, Any]:
        """获取 Layer 1 索引条目（不触发完整 YAML 加载）。

        Raises:
            PluginNotFoundError: tool_id 不在索引中。
        """
        if tool_id not in self._index:
            raise PluginNotFoundError(f"未找到插件: {tool_id}")
        return {"id": tool_id, **self._index[tool_id]}

    @property
    def plugin_count(self) -> int:
        """已注册插件数量。"""
        return len(self._index)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _read_header(yaml_path: Path) -> Dict[str, Any]:
        """快速读取 tool.yaml 的头部字段。

        仅提取 _HEADER_KEYS 中定义的字段，避免全量解析。
        对于小文件来说全量解析也可接受，但语义上只需要头部。
        """
        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            raise ValueError(f"tool.yaml 格式错误（非字典）: {yaml_path}")

        if "id" not in data:
            raise ValueError(f"tool.yaml 缺少必填字段 'id': {yaml_path}")

        return {k: data[k] for k in _HEADER_KEYS if k in data}
