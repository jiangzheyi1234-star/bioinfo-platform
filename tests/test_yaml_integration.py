# tests/test_yaml_integration.py
"""YAML 集成测试 — 端到端验证 PluginRegistry + CommandBuilder 链路。

对每个真实 tool.yaml 执行:
  1. PluginRegistry 加载描述符
  2. CommandBuilder.merge_defaults() 合并参数
  3. CommandBuilder.build() 渲染命令
  4. CommandBuilder.wrap() 生成包装脚本
  5. 验证工具名、参数、conda 环境、输出路径等正确性
"""
import shlex
from pathlib import Path

import pytest

from core.execution.command_builder import CommandBuilder, HEARTBEAT_INTERVAL
from core.plugins.plugin_registry import PluginRegistry

# 项目真实 plugins 目录
_PLUGINS_DIR = Path(__file__).parent.parent / "plugins"
_MANAGED_CONDA = "/home/user/.h2ometa/conda/bin/conda"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    """加载真实 plugins 目录，整个模块共享。"""
    if not _PLUGINS_DIR.is_dir():
        pytest.skip("plugins 目录不存在")
    reg = PluginRegistry(_PLUGINS_DIR)
    count = reg.scan()
    assert count >= 4, f"预期至少 4 个插件，实际扫描到 {count}"
    return reg


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _build_and_wrap(
    registry: PluginRegistry,
    tool_id: str,
    input_paths: dict[str, str],
    user_params: dict | None = None,
    database_paths: dict[str, str] | None = None,
    sample_id: str = "sample_001",
    output_dir: str = "/h2ometa/projects/proj_001/intermediate/sample_001",
) -> tuple[dict, dict, str, str, str]:
    """执行完整的 加载→合并→构建→包装 流程。

    Returns:
        (descriptor, merged_params, command, wrapped_script, output_paths)
    """
    descriptor = registry.get_descriptor(tool_id)
    merged = CommandBuilder.merge_defaults(descriptor, user_params or {})
    output_paths = CommandBuilder.resolve_output_paths(descriptor, output_dir, sample_id)

    # 将输出路径也加入 input_paths（模板中会引用输出变量名如 clean_1, report_html）
    all_paths = {**input_paths, **output_paths}

    command = CommandBuilder.build(
        descriptor=descriptor,
        parameters=merged,
        input_paths=all_paths,
        output_dir=output_dir,
        sample_id=sample_id,
        database_paths=database_paths,
        conda_executable=_MANAGED_CONDA,
    )
    job_id = f"h2o_test_{tool_id}"
    task_dir = f"/tmp/h2ometa/{job_id}"
    wrapped = CommandBuilder.wrap(command, job_id, task_dir)
    return descriptor, merged, command, wrapped, output_paths


# ---------------------------------------------------------------------------
# fastp 端到端测试
# ---------------------------------------------------------------------------

class TestFastpIntegration:
    """fastp tool.yaml 集成测试。"""

    TOOL_ID = "fastp"

    def test_descriptor_loaded(self, registry: PluginRegistry) -> None:
        """PluginRegistry 能正确加载 fastp 描述符。"""
        desc = registry.get_descriptor(self.TOOL_ID)
        assert desc["id"] == "fastp"
        assert desc["version"] == "0.23.4"
        assert desc["category"] == "qc"
        assert desc["conda_env"] == "fastp_env"

    def test_build_single_end(self, registry: PluginRegistry) -> None:
        """单端模式: reads_2 不存在时不应渲染 -I / -O 参数。"""
        _, merged, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/s1.R1.fq.gz"},
        )
        assert "fastp" in cmd
        assert "-i /data/s1.R1.fq.gz" in cmd
        assert "-q 20" in cmd  # 默认值
        assert "-l 50" in cmd  # 默认值
        assert "-w 4" in cmd   # 默认值
        assert "conda run -p ~/.h2ometa/conda/envs/fastp_env" in cmd
        # 单端: 不应有 -I
        assert "-I " not in cmd

    def test_build_paired_end(self, registry: PluginRegistry) -> None:
        """双端模式: reads_2 存在时应渲染 -I / -O 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={
                "reads_1": "/data/s1.R1.fq.gz",
                "reads_2": "/data/s1.R2.fq.gz",
            },
        )
        assert "-I /data/s1.R2.fq.gz" in cmd
        assert "-O " in cmd

    def test_user_params_override(self, registry: PluginRegistry) -> None:
        """用户参数应覆盖默认值。"""
        _, merged, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/s1.R1.fq.gz"},
            user_params={"qualified_quality_phred": 20, "length_required": 100, "thread": 8},
        )
        assert merged["qualified_quality_phred"] == 20
        assert merged["length_required"] == 100
        assert merged["thread"] == 8
        assert "-q 20" in cmd
        assert "-l 100" in cmd
        assert "-w 8" in cmd

    def test_output_paths_resolved(self, registry: PluginRegistry) -> None:
        """输出路径模板中的 {output_dir}/{sample_id} 应被正确替换。"""
        _, _, _, _, out_paths = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
            sample_id="WS01",
            output_dir="/proj/inter/WS01/fastp",
        )
        assert out_paths["clean_1"] == "/proj/inter/WS01/fastp/WS01.clean.R1.fq.gz"
        assert out_paths["clean_2"] == "/proj/inter/WS01/fastp/WS01.clean.R2.fq.gz"
        assert out_paths["report_html"] == "/proj/inter/WS01/fastp/WS01.fastp.html"
        assert out_paths["report_json"] == "/proj/inter/WS01/fastp/WS01.fastp.json"

    def test_html_and_json_report_in_cmd(self, registry: PluginRegistry) -> None:
        """命令中应包含 -h (HTML报告) 和 -j (JSON报告) 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
            sample_id="s1",
            output_dir="/out",
        )
        assert "-h /out/s1.fastp.html" in cmd
        assert "-j /out/s1.fastp.json" in cmd

    def test_wrap_contains_full_pipeline(self, registry: PluginRegistry) -> None:
        """包装脚本应包含完整的生命周期管理。"""
        _, _, _, wrapped, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
        )
        assert "set -euo pipefail" in wrapped
        assert 'echo "RUNNING"' in wrapped
        assert "trap _cleanup EXIT" in wrapped
        assert f"sleep {HEARTBEAT_INTERVAL}" in wrapped
        assert "fastp" in wrapped
        assert "conda run -p ~/.h2ometa/conda/envs/fastp_env" in wrapped


# ---------------------------------------------------------------------------
# kraken2 端到端测试
# ---------------------------------------------------------------------------

class TestKraken2Integration:
    """kraken2 tool.yaml 集成测试。"""

    TOOL_ID = "kraken2"

    def test_descriptor_loaded(self, registry: PluginRegistry) -> None:
        """PluginRegistry 能正确加载 kraken2 描述符。"""
        desc = registry.get_descriptor(self.TOOL_ID)
        assert desc["id"] == "kraken2"
        assert desc["version"] == "2.1.3"
        assert desc["category"] == "taxonomy"
        assert desc["conda_env"] == "kraken2_env"
        assert len(desc["databases"]) == 1
        assert desc["databases"][0]["param_name"] == "db"

    def test_build_with_database(self, registry: PluginRegistry) -> None:
        """kraken2 需要数据库路径，build 后应包含 --db 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/s1.clean.fq.gz"},
            database_paths={"db": "/h2ometa/databases/kraken2_standard"},
        )
        assert "kraken2" in cmd
        assert "--db /h2ometa/databases/kraken2_standard" in cmd
        assert "--threads 8" in cmd   # 默认值
        assert "--confidence 0.1" in cmd  # 默认值
        assert "--minimum-hit-groups 2" in cmd  # 默认值
        assert "conda run -p ~/.h2ometa/conda/envs/kraken2_env" in cmd

    def test_build_input_reads_alias(self, registry: PluginRegistry) -> None:
        """模板使用 {input_reads}，应通过 input_ 前缀别名解析。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/qc_output.fq.gz"},
            database_paths={"db": "/db/k2"},
        )
        assert "/data/qc_output.fq.gz" in cmd

    def test_user_params_confidence(self, registry: PluginRegistry) -> None:
        """用户自定义 confidence 阈值。"""
        _, merged, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/r.fq"},
            database_paths={"db": "/db/k2"},
            user_params={"confidence": 0.5, "threads": 16},
        )
        assert merged["confidence"] == 0.5
        assert merged["threads"] == 16
        assert "--confidence 0.5" in cmd
        assert "--threads 16" in cmd

    def test_output_paths_contain_kreport(self, registry: PluginRegistry) -> None:
        """输出路径应包含 .kreport 和 .k2output。"""
        _, _, _, _, out_paths = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/r.fq"},
            database_paths={"db": "/db/k2"},
            sample_id="env_water_01",
            output_dir="/proj/inter/env_water_01/kraken2",
        )
        assert out_paths["k2_report"] == "/proj/inter/env_water_01/kraken2/env_water_01.kreport"
        assert out_paths["k2_output"] == "/proj/inter/env_water_01/kraken2/env_water_01.k2output"

    def test_report_and_output_in_cmd(self, registry: PluginRegistry) -> None:
        """命令中应包含 --report 和 --output 路径。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/r.fq"},
            database_paths={"db": "/db/k2"},
            sample_id="s1",
            output_dir="/out",
        )
        assert "--report /out/s1.kreport" in cmd
        assert "--output /out/s1.k2output" in cmd

    def test_wrap_contains_kraken2(self, registry: PluginRegistry) -> None:
        """包装脚本应包含 kraken2 命令和 conda 环境。"""
        _, _, _, wrapped, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads": "/data/r.fq"},
            database_paths={"db": "/db/k2"},
        )
        assert "kraken2" in wrapped
        assert "conda run -p ~/.h2ometa/conda/envs/kraken2_env" in wrapped
        assert "trap _cleanup EXIT" in wrapped


# ---------------------------------------------------------------------------
# checkm2 / gtdbtk 数据库绑定测试
# ---------------------------------------------------------------------------

class TestQualityAndTaxonomyDatabaseBindings:
    """验证数据库参数在真实 tool.yaml 中的消费语义。"""

    def test_checkm2_consumes_database_path(self, registry: PluginRegistry) -> None:
        """CheckM2 应显式消费 database_path 并指向 dmnd 文件。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            "checkm2",
            input_paths={"bins_dir": "/data/bins"},
            database_paths={"database_path": "/data/databases/checkm2"},
        )
        assert "--database_path /data/databases/checkm2/uniref100.KO.1.dmnd" in cmd
        assert "checkm2 predict" in cmd

    def test_gtdbtk_exports_gtdbtk_data_path(self, registry: PluginRegistry) -> None:
        """GTDB-Tk 应显式导出 GTDBTK_DATA_PATH，而不是依赖 mash_db。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            "gtdbtk",
            input_paths={"bins_dir": "/data/bins"},
            database_paths={"db": "/data/databases/gtdbtk/release220"},
        )
        assert 'export GTDBTK_DATA_PATH="/data/databases/gtdbtk/release220"' in cmd
        assert "--mash_db" not in cmd
        assert "gtdbtk classify_wf" in cmd


# ---------------------------------------------------------------------------
# hostile 端到端测试
# ---------------------------------------------------------------------------

class TestHostileIntegration:
    """hostile tool.yaml 集成测试。"""

    TOOL_ID = "hostile"

    def test_descriptor_loaded(self, registry: PluginRegistry) -> None:
        """PluginRegistry 能正确加载 hostile 描述符。"""
        desc = registry.get_descriptor(self.TOOL_ID)
        assert desc["id"] == "hostile"
        assert desc["version"] == "1.1.0"
        assert desc["category"] == "host_removal"
        assert desc["conda_env"] == "hostile_env"
        assert desc["databases"] == []

    def test_build_single_end(self, registry: PluginRegistry) -> None:
        """单端模式: 不应有 --fastq2 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/s1.clean.R1.fq.gz"},
        )
        assert "hostile clean" in cmd
        assert "--fastq1 /data/s1.clean.R1.fq.gz" in cmd
        assert "--aligner bowtie2" in cmd     # 默认值
        assert "--index human-t2t-hla" in cmd  # 默认值
        assert "--threads 8" in cmd            # 默认值
        assert "conda run -p ~/.h2ometa/conda/envs/hostile_env" in cmd
        assert "--fastq2" not in cmd

    def test_build_paired_end(self, registry: PluginRegistry) -> None:
        """双端模式: reads_2 存在时应渲染 --fastq2 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={
                "reads_1": "/data/s1.R1.fq.gz",
                "reads_2": "/data/s1.R2.fq.gz",
            },
        )
        assert "--fastq1 /data/s1.R1.fq.gz" in cmd
        assert "--fastq2 /data/s1.R2.fq.gz" in cmd

    def test_user_selects_minimap2(self, registry: PluginRegistry) -> None:
        """用户切换为 minimap2 比对器。"""
        _, merged, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
            user_params={"aligner": "minimap2", "threads": 16},
        )
        assert merged["aligner"] == "minimap2"
        assert "--aligner minimap2" in cmd
        assert "--threads 16" in cmd

    def test_output_dir_in_cmd(self, registry: PluginRegistry) -> None:
        """命令中应包含 --out-dir 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
            output_dir="/proj/inter/s1/hostile",
        )
        assert "--out-dir /proj/inter/s1/hostile" in cmd

    def test_output_paths_resolved(self, registry: PluginRegistry) -> None:
        """输出路径模板应被正确替换。"""
        _, _, _, _, out_paths = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
            sample_id="s1",
            output_dir="/out",
        )
        assert out_paths["clean_1"] == "/out/s1.host_removed.R1.fq.gz"
        assert out_paths["clean_2"] == "/out/s1.host_removed.R2.fq.gz"

    def test_wrap_full_pipeline(self, registry: PluginRegistry) -> None:
        """包装脚本应包含 hostile 命令和完整生命周期。"""
        _, _, _, wrapped, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"reads_1": "/data/r1.fq"},
        )
        assert "hostile clean" in wrapped
        assert "conda run -p ~/.h2ometa/conda/envs/hostile_env" in wrapped
        assert 'echo "RUNNING"' in wrapped
        assert 'echo "DONE"' in wrapped


# ---------------------------------------------------------------------------
# blastn 端到端测试
# ---------------------------------------------------------------------------

class TestBlastnIntegration:
    """blastn tool.yaml 集成测试。"""

    TOOL_ID = "blastn"

    def test_descriptor_loaded(self, registry: PluginRegistry) -> None:
        """PluginRegistry 能正确加载 blastn 描述符。"""
        desc = registry.get_descriptor(self.TOOL_ID)
        assert desc["id"] == "blastn"
        assert desc["version"] == "2.15.0"
        assert desc["category"] == "blast"
        assert desc["conda_env"] == "blast_env"
        assert len(desc["databases"]) == 1
        assert desc["databases"][0]["param_name"] == "db"

    def test_build_with_database(self, registry: PluginRegistry) -> None:
        """blastn 需要数据库路径，build 后应包含 -db 参数。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/query.fa"},
            database_paths={"db": "/h2ometa/databases/nt"},
        )
        assert "blastn" in cmd
        assert "-query /data/query.fa" in cmd
        assert "-db /h2ometa/databases/nt" in cmd
        assert "-evalue 1e-05" in cmd or "-evalue 1.0e-05" in cmd  # 浮点格式
        assert "-max_target_seqs 10" in cmd
        assert "-num_threads 4" in cmd
        assert "conda run -p ~/.h2ometa/conda/envs/blast_env" in cmd

    def test_build_input_query_alias(self, registry: PluginRegistry) -> None:
        """模板使用 {input_query}，应通过 input_ 前缀别名解析。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/my_seqs.fasta"},
            database_paths={"db": "/db/nt"},
        )
        assert "/data/my_seqs.fasta" in cmd

    def test_user_params_evalue_and_threads(self, registry: PluginRegistry) -> None:
        """用户自定义 evalue 和线程数。"""
        _, merged, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/q.fa"},
            database_paths={"db": "/db/nt"},
            user_params={"evalue": 1e-10, "threads": 16, "max_target_seqs": 50},
        )
        assert merged["evalue"] == 1e-10
        assert merged["threads"] == 16
        assert merged["max_target_seqs"] == 50
        assert "-num_threads 16" in cmd
        assert "-max_target_seqs 50" in cmd

    def test_outfmt_in_cmd(self, registry: PluginRegistry) -> None:
        """默认 outfmt 应包含标准 BLAST 表格字段。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/q.fa"},
            database_paths={"db": "/db/nt"},
        )
        assert "qseqid" in cmd
        assert "sseqid" in cmd
        assert "pident" in cmd
        assert "evalue" in cmd
        assert "bitscore" in cmd

    def test_output_paths_resolved(self, registry: PluginRegistry) -> None:
        """输出路径应包含 .blastn.tsv。"""
        _, _, _, _, out_paths = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/q.fa"},
            database_paths={"db": "/db/nt"},
            sample_id="iso_42",
            output_dir="/proj/inter/iso_42/blastn",
        )
        assert out_paths["blast_result"] == "/proj/inter/iso_42/blastn/iso_42.blastn.tsv"

    def test_output_path_in_cmd(self, registry: PluginRegistry) -> None:
        """命令中 -out 应指向正确的输出文件。"""
        _, _, cmd, _, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/q.fa"},
            database_paths={"db": "/db/nt"},
            sample_id="s1",
            output_dir="/out",
        )
        assert "-out /out/s1.blastn.tsv" in cmd

    def test_wrap_full_pipeline(self, registry: PluginRegistry) -> None:
        """包装脚本应包含 blastn 命令和完整生命周期。"""
        _, _, _, wrapped, _ = _build_and_wrap(
            registry,
            self.TOOL_ID,
            input_paths={"query": "/data/q.fa"},
            database_paths={"db": "/db/nt"},
        )
        assert "blastn" in wrapped
        assert "conda run -p ~/.h2ometa/conda/envs/blast_env" in wrapped
        assert "set -euo pipefail" in wrapped
        assert "trap _cleanup EXIT" in wrapped
        assert f"sleep {HEARTBEAT_INTERVAL}" in wrapped
        assert 'echo "DONE"' in wrapped
        assert 'echo "FAILED"' in wrapped


# ---------------------------------------------------------------------------
# 跨工具通用验证
# ---------------------------------------------------------------------------

class TestCrossToolValidation:
    """跨所有 tool.yaml 的通用约束验证。"""

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_all_tools_have_conda_env(self, registry: PluginRegistry, tool_id: str) -> None:
        """所有工具应声明 conda_env。"""
        desc = registry.get_descriptor(tool_id)
        assert desc.get("conda_env"), f"{tool_id} 缺少 conda_env"

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_all_tools_have_detection(self, registry: PluginRegistry, tool_id: str) -> None:
        """所有工具应声明 detection 配置。"""
        desc = registry.get_descriptor(tool_id)
        assert "detection" in desc
        assert "command" in desc["detection"]
        assert "version_regex" in desc["detection"]

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_all_tools_have_methods_template(self, registry: PluginRegistry, tool_id: str) -> None:
        """所有工具应声明 methods_template（论文生成用）。"""
        desc = registry.get_descriptor(tool_id)
        assert desc.get("methods_template"), f"{tool_id} 缺少 methods_template"

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_merge_defaults_covers_all_params(self, registry: PluginRegistry, tool_id: str) -> None:
        """merge_defaults 空用户参数时应覆盖所有声明的参数。"""
        desc = registry.get_descriptor(tool_id)
        merged = CommandBuilder.merge_defaults(desc, {})
        param_names = {p["name"] for p in desc.get("parameters", [])}
        assert set(merged.keys()) == param_names, (
            f"{tool_id}: 合并后缺少参数 {param_names - set(merged.keys())}"
        )

    @pytest.mark.parametrize("tool_id", ["fastp", "kraken2", "hostile", "blastn"])
    def test_wrap_always_has_lifecycle(self, registry: PluginRegistry, tool_id: str) -> None:
        """所有工具的包装脚本应包含完整生命周期标记。"""
        desc = registry.get_descriptor(tool_id)
        # 用最简输入构建一个命令
        cmd = "echo placeholder"
        wrapped = CommandBuilder.wrap(cmd, f"h2o_{tool_id}", f"/tmp/{tool_id}")
        assert "RUNNING" in wrapped
        assert "DONE" in wrapped
        assert "FAILED" in wrapped
        assert "exit_code" in wrapped.lower()
        assert "heartbeat" in wrapped.lower()

    def test_all_conda_create_install_cmds_do_not_inline_channels(
        self,
        registry: PluginRegistry,
    ) -> None:
        """真实工具插件的 conda create install_cmd 不应内联 channel。"""
        forbidden = {"-c", "--channel", "--override-channels"}

        for tool_id in registry.list_all_ids():
            desc = registry.get_descriptor(tool_id)
            install_cmd = str(desc.get("install_cmd", "") or "").strip()
            if not install_cmd:
                continue

            tokens = shlex.split(install_cmd, posix=True)
            if len(tokens) < 2 or tokens[1] != "create" or not tokens[0].endswith("conda"):
                continue

            found = [
                token for token in tokens
                if token in forbidden or token.startswith("--channel=")
            ]
            assert not found, f"{tool_id} install_cmd 仍内联 channel: {install_cmd}"
