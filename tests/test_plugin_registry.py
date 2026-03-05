# tests/test_plugin_registry.py
"""PluginRegistry 单元测试 — 覆盖扫描、懒加载、查询、错误处理等场景。"""
import textwrap
from pathlib import Path

import pytest
import yaml

from core.plugin_registry import PluginNotFoundError, PluginRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def plugins_dir(tmp_path: Path) -> Path:
    """创建一个包含多个 tool.yaml 的临时插件目录。"""
    # fastp — qc 分类
    fastp_dir = tmp_path / "qc" / "fastp"
    fastp_dir.mkdir(parents=True)
    (fastp_dir / "tool.yaml").write_text(
        yaml.dump({
            "id": "fastp",
            "name": "fastp",
            "version": "0.23.4",
            "category": "qc",
            "description": "超快速 FASTQ 质量控制",
            "conda_env": "fastp_env",
            "inputs": [
                {"name": "reads_1", "type": "fastq", "required": True},
            ],
            "outputs": [
                {"name": "clean_1", "type": "fastq", "tier": "intermediate",
                 "pattern": "{output_dir}/{sample_id}.clean.R1.fq.gz"},
            ],
            "parameters": [
                {"name": "thread", "type": "int", "default": 4},
            ],
            "command_template": "fastp -i {reads_1} -o {clean_1} -w {thread}",
            "databases": [],
            "detection": {
                "command": "fastp --version",
                "version_regex": r"fastp (\d+\.\d+\.\d+)",
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )

    # kraken2 — taxonomy 分类
    kraken2_dir = tmp_path / "taxonomy" / "kraken2"
    kraken2_dir.mkdir(parents=True)
    (kraken2_dir / "tool.yaml").write_text(
        yaml.dump({
            "id": "kraken2",
            "name": "Kraken2",
            "version": "2.1.3",
            "category": "taxonomy",
            "description": "超快速 k-mer 物种分类",
            "conda_env": "kraken2_env",
            "inputs": [
                {"name": "reads", "type": "fastq", "required": True},
            ],
            "outputs": [
                {"name": "k2_report", "type": "kreport", "tier": "result",
                 "pattern": "{output_dir}/{sample_id}.kreport"},
            ],
            "parameters": [
                {"name": "confidence", "type": "float", "default": 0.0},
                {"name": "threads", "type": "int", "default": 8},
            ],
            "command_template": "kraken2 --db {db} --threads {threads} {input_reads}",
            "databases": [
                {"id": "kraken2_standard", "param_name": "db", "required": True},
            ],
            "detection": {
                "command": "kraken2 --version",
                "version_regex": r"version (\d+\.\d+\.\d+)",
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )

    # hostile — host_removal 分类
    hostile_dir = tmp_path / "host_removal" / "hostile"
    hostile_dir.mkdir(parents=True)
    (hostile_dir / "tool.yaml").write_text(
        yaml.dump({
            "id": "hostile",
            "name": "Hostile",
            "version": "1.1.0",
            "category": "host_removal",
            "description": "宿主序列去除",
            "conda_env": "hostile_env",
            "inputs": [
                {"name": "reads_1", "type": "fastq", "required": True},
            ],
            "outputs": [
                {"name": "clean_1", "type": "fastq", "tier": "intermediate",
                 "pattern": "{output_dir}/{sample_id}.host_removed.R1.fq.gz"},
            ],
            "parameters": [
                {"name": "threads", "type": "int", "default": 4},
            ],
            "command_template": "hostile clean --fastq1 {reads_1} --threads {threads}",
            "databases": [],
            "detection": {
                "command": "hostile --version",
                "version_regex": r"hostile (\d+\.\d+\.\d+)",
            },
        }, allow_unicode=True),
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture()
def registry(plugins_dir: Path) -> PluginRegistry:
    """创建并扫描好的 PluginRegistry 实例。"""
    reg = PluginRegistry(plugins_dir)
    reg.scan()
    return reg


# ---------------------------------------------------------------------------
# 扫描测试
# ---------------------------------------------------------------------------

class TestScan:
    """Layer 1 扫描相关测试。"""

    def test_scan_finds_all_plugins(self, registry: PluginRegistry) -> None:
        """扫描应发现所有 tool.yaml 文件。"""
        assert registry.plugin_count == 3

    def test_scan_returns_count(self, plugins_dir: Path) -> None:
        """scan() 应返回成功扫描的插件数量。"""
        reg = PluginRegistry(plugins_dir)
        count = reg.scan()
        assert count == 3

    def test_list_all_ids(self, registry: PluginRegistry) -> None:
        """list_all_ids 应返回所有插件 ID。"""
        ids = registry.list_all_ids()
        assert set(ids) == {"fastp", "kraken2", "hostile"}

    def test_scan_nonexistent_dir(self, tmp_path: Path) -> None:
        """扫描不存在的目录应返回 0，不抛异常。"""
        reg = PluginRegistry(tmp_path / "nonexistent")
        count = reg.scan()
        assert count == 0
        assert reg.plugin_count == 0

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        """扫描空目录应返回 0。"""
        empty_dir = tmp_path / "empty_plugins"
        empty_dir.mkdir()
        reg = PluginRegistry(empty_dir)
        count = reg.scan()
        assert count == 0

    def test_scan_clears_previous_state(self, registry: PluginRegistry, plugins_dir: Path) -> None:
        """重复扫描应清除旧状态。"""
        # 先加载一个描述符（缓存到 Layer 2）
        registry.get_descriptor("fastp")
        # 重新扫描
        registry.scan()
        # Layer 2 缓存应被清除
        assert registry.plugin_count == 3

    def test_scan_skips_invalid_yaml(self, tmp_path: Path) -> None:
        """包含无效 YAML 的文件应被跳过，不影响其他插件。"""
        # 有效插件
        valid_dir = tmp_path / "qc" / "fastp"
        valid_dir.mkdir(parents=True)
        (valid_dir / "tool.yaml").write_text(
            yaml.dump({"id": "fastp", "name": "fastp", "category": "qc"}),
            encoding="utf-8",
        )
        # 无效 YAML（非字典）
        bad_dir = tmp_path / "bad" / "tool"
        bad_dir.mkdir(parents=True)
        (bad_dir / "tool.yaml").write_text("- just a list\n- not a dict\n", encoding="utf-8")

        reg = PluginRegistry(tmp_path)
        count = reg.scan()
        assert count == 1
        assert reg.list_all_ids() == ["fastp"]

    def test_scan_skips_missing_id(self, tmp_path: Path) -> None:
        """缺少 id 字段的 tool.yaml 应被跳过。"""
        no_id_dir = tmp_path / "bad" / "noid"
        no_id_dir.mkdir(parents=True)
        (no_id_dir / "tool.yaml").write_text(
            yaml.dump({"name": "NoId", "category": "test"}),
            encoding="utf-8",
        )
        reg = PluginRegistry(tmp_path)
        count = reg.scan()
        assert count == 0

    def test_scan_duplicate_id_keeps_first(self, tmp_path: Path) -> None:
        """相同 ID 的插件，仅保留第一个扫描到的。"""
        dir_a = tmp_path / "a_first" / "fastp"
        dir_a.mkdir(parents=True)
        (dir_a / "tool.yaml").write_text(
            yaml.dump({"id": "fastp", "name": "fastp-A", "category": "qc"}),
            encoding="utf-8",
        )
        dir_b = tmp_path / "b_second" / "fastp"
        dir_b.mkdir(parents=True)
        (dir_b / "tool.yaml").write_text(
            yaml.dump({"id": "fastp", "name": "fastp-B", "category": "qc"}),
            encoding="utf-8",
        )
        reg = PluginRegistry(tmp_path)
        count = reg.scan()
        assert count == 1
        # rglob + sorted => a_first 排在 b_second 前面
        entry = reg.get_index_entry("fastp")
        assert entry["name"] == "fastp-A"


# ---------------------------------------------------------------------------
# 按分类查询测试
# ---------------------------------------------------------------------------

class TestListByCategory:
    """list_by_category 相关测试。"""

    def test_filter_qc(self, registry: PluginRegistry) -> None:
        """按 qc 分类过滤。"""
        results = registry.list_by_category("qc")
        assert len(results) == 1
        assert results[0]["id"] == "fastp"

    def test_filter_taxonomy(self, registry: PluginRegistry) -> None:
        """按 taxonomy 分类过滤。"""
        results = registry.list_by_category("taxonomy")
        assert len(results) == 1
        assert results[0]["id"] == "kraken2"

    def test_filter_nonexistent_category(self, registry: PluginRegistry) -> None:
        """不存在的分类应返回空列表。"""
        results = registry.list_by_category("nonexistent")
        assert results == []

    def test_category_entry_contains_expected_keys(self, registry: PluginRegistry) -> None:
        """返回的条目应包含 id, name, category, version, description, path。"""
        results = registry.list_by_category("qc")
        entry = results[0]
        assert "id" in entry
        assert "name" in entry
        assert "category" in entry
        assert "version" in entry
        assert "path" in entry


# ---------------------------------------------------------------------------
# 描述符（Layer 2）测试
# ---------------------------------------------------------------------------

class TestGetDescriptor:
    """get_descriptor 懒加载测试。"""

    def test_loads_full_yaml(self, registry: PluginRegistry) -> None:
        """get_descriptor 应返回完整 YAML 内容。"""
        desc = registry.get_descriptor("fastp")
        assert desc["id"] == "fastp"
        assert desc["conda_env"] == "fastp_env"
        assert isinstance(desc["inputs"], list)
        assert isinstance(desc["parameters"], list)
        assert "command_template" in desc

    def test_lazy_loading(self, registry: PluginRegistry) -> None:
        """描述符应仅在首次调用时加载。"""
        # 首次调用前，_descriptors 应为空
        assert "fastp" not in registry._descriptors
        registry.get_descriptor("fastp")
        assert "fastp" in registry._descriptors

    def test_cached_on_second_call(self, registry: PluginRegistry) -> None:
        """第二次调用应返回缓存对象。"""
        desc1 = registry.get_descriptor("fastp")
        desc2 = registry.get_descriptor("fastp")
        assert desc1 is desc2

    def test_not_found_raises_error(self, registry: PluginRegistry) -> None:
        """请求不存在的插件应抛出 PluginNotFoundError。"""
        with pytest.raises(PluginNotFoundError, match="未找到插件"):
            registry.get_descriptor("nonexistent_tool")

    def test_descriptor_has_detection(self, registry: PluginRegistry) -> None:
        """描述符应包含 detection 信息。"""
        desc = registry.get_descriptor("kraken2")
        assert "detection" in desc
        assert "command" in desc["detection"]
        assert "version_regex" in desc["detection"]

    def test_descriptor_databases(self, registry: PluginRegistry) -> None:
        """描述符应包含正确的 databases 依赖。"""
        desc = registry.get_descriptor("kraken2")
        assert len(desc["databases"]) == 1
        assert desc["databases"][0]["id"] == "kraken2_standard"
        assert desc["databases"][0]["param_name"] == "db"


# ---------------------------------------------------------------------------
# get_index_entry 测试
# ---------------------------------------------------------------------------

class TestGetIndexEntry:
    """get_index_entry 测试。"""

    def test_returns_entry_without_loading_descriptor(self, registry: PluginRegistry) -> None:
        """获取索引条目不应触发 Layer 2 加载。"""
        entry = registry.get_index_entry("fastp")
        assert entry["id"] == "fastp"
        assert entry["category"] == "qc"
        # Layer 2 不应被加载
        assert "fastp" not in registry._descriptors

    def test_not_found_raises_error(self, registry: PluginRegistry) -> None:
        """请求不存在的插件应抛出 PluginNotFoundError。"""
        with pytest.raises(PluginNotFoundError):
            registry.get_index_entry("nonexistent")


# ---------------------------------------------------------------------------
# 真实 tool.yaml 文件测试（集成测试）
# ---------------------------------------------------------------------------

class TestRealToolYaml:
    """测试项目中实际的 tool.yaml 文件。"""

    @pytest.fixture()
    def real_registry(self) -> PluginRegistry:
        """使用项目真实的 plugins 目录。"""
        plugins_dir = Path(__file__).parent.parent / "plugins"
        if not plugins_dir.is_dir():
            pytest.skip("plugins 目录不存在")
        reg = PluginRegistry(plugins_dir)
        reg.scan()
        return reg

    def test_scan_real_plugins(self, real_registry: PluginRegistry) -> None:
        """项目应包含 4 个真实插件。"""
        assert real_registry.plugin_count == 4
        ids = set(real_registry.list_all_ids())
        assert ids == {"fastp", "kraken2", "hostile", "blastn"}

    def test_real_categories(self, real_registry: PluginRegistry) -> None:
        """真实插件应分布在 4 个不同分类中。"""
        assert len(real_registry.list_by_category("qc")) == 1
        assert len(real_registry.list_by_category("taxonomy")) == 1
        assert len(real_registry.list_by_category("host_removal")) == 1
        assert len(real_registry.list_by_category("blast")) == 1

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_real_descriptor_structure(self, real_registry: PluginRegistry, tool_id: str) -> None:
        """每个真实插件的描述符应包含必要字段。"""
        desc = real_registry.get_descriptor(tool_id)
        # 必填字段
        assert "id" in desc
        assert "name" in desc
        assert "version" in desc
        assert "category" in desc
        assert "conda_env" in desc
        assert "inputs" in desc
        assert "outputs" in desc
        assert "parameters" in desc
        assert "command_template" in desc
        assert "detection" in desc
        # inputs/outputs 应为非空列表
        assert len(desc["inputs"]) >= 1
        assert len(desc["outputs"]) >= 1

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_real_descriptor_detection(self, real_registry: PluginRegistry, tool_id: str) -> None:
        """每个插件应有检测命令和版本正则。"""
        desc = real_registry.get_descriptor(tool_id)
        detection = desc["detection"]
        assert "command" in detection
        assert "version_regex" in detection
