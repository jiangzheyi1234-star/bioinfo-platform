# tests/test_command_builder.py
"""CommandBuilder 单元测试 — 覆盖模板渲染、参数合并、包装脚本生成等场景。"""
import pytest

from core.command_builder import CommandBuildError, CommandBuilder, HEARTBEAT_INTERVAL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fastp_descriptor() -> dict:
    """模拟 fastp 的完整 tool.yaml 描述符。"""
    return {
        "id": "fastp",
        "name": "fastp",
        "version": "0.23.4",
        "category": "qc",
        "conda_env": "fastp_env",
        "inputs": [
            {"name": "reads_1", "type": "fastq", "required": True},
            {"name": "reads_2", "type": "fastq", "required": False},
        ],
        "outputs": [
            {"name": "clean_1", "type": "fastq", "tier": "intermediate",
             "pattern": "{output_dir}/{sample_id}.clean.R1.fq.gz"},
            {"name": "clean_2", "type": "fastq", "tier": "intermediate",
             "pattern": "{output_dir}/{sample_id}.clean.R2.fq.gz"},
            {"name": "report_html", "type": "html", "tier": "result",
             "pattern": "{output_dir}/{sample_id}.fastp.html"},
        ],
        "parameters": [
            {"name": "qualified_quality_phred", "type": "int", "default": 15},
            {"name": "length_required", "type": "int", "default": 50},
            {"name": "thread", "type": "int", "default": 4},
        ],
        "command_template": (
            "fastp -i {{ reads_1 }} -o {{ clean_1 }} "
            "-q {{ qualified_quality_phred }} -l {{ length_required }} -w {{ thread }}"
        ),
    }


@pytest.fixture()
def kraken2_descriptor() -> dict:
    """模拟 kraken2 的描述符（带数据库依赖）。"""
    return {
        "id": "kraken2",
        "name": "Kraken2",
        "version": "2.1.3",
        "category": "taxonomy",
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
        "command_template": (
            "kraken2 --db {{ db }} --threads {{ threads }} "
            "--confidence {{ confidence }} {{ input_reads }}"
        ),
        "databases": [
            {"id": "kraken2_standard", "param_name": "db", "required": True},
        ],
    }


@pytest.fixture()
def simple_descriptor() -> dict:
    """最简模板，用于测试基本渲染。"""
    return {
        "id": "simple_tool",
        "name": "Simple",
        "version": "1.0",
        "category": "test",
        "inputs": [{"name": "input_file", "type": "txt", "required": True}],
        "outputs": [{"name": "output_file", "type": "txt", "tier": "result",
                      "pattern": "{output_dir}/{sample_id}.out"}],
        "parameters": [{"name": "flag", "type": "string", "default": "hello"}],
        "command_template": "simple_tool --input {{ input_file }} --flag {{ flag }}",
    }


# ---------------------------------------------------------------------------
# build() 测试
# ---------------------------------------------------------------------------

class TestBuild:
    """CommandBuilder.build() 模板渲染测试。"""

    def test_basic_render(self, simple_descriptor: dict) -> None:
        """基本渲染: 变量替换正确。"""
        cmd = CommandBuilder.build(
            descriptor=simple_descriptor,
            parameters={"flag": "world"},
            input_paths={"input_file": "/data/test.txt"},
            output_dir="/output",
            sample_id="s001",
        )
        assert "simple_tool" in cmd
        assert "--input /data/test.txt" in cmd
        assert "--flag world" in cmd

    def test_fastp_render(self, fastp_descriptor: dict) -> None:
        """渲染 fastp 命令: 包含所有参数。"""
        cmd = CommandBuilder.build(
            descriptor=fastp_descriptor,
            parameters={"qualified_quality_phred": 20, "length_required": 60, "thread": 8},
            input_paths={
                "reads_1": "/data/s1.R1.fq.gz",
                "clean_1": "/out/s1.clean.R1.fq.gz",
            },
            output_dir="/out",
            sample_id="s1",
        )
        assert "-i /data/s1.R1.fq.gz" in cmd
        assert "-q 20" in cmd
        assert "-l 60" in cmd
        assert "-w 8" in cmd

    def test_conda_env_wrapping(self, fastp_descriptor: dict) -> None:
        """有 conda_env 时应包装 conda run。"""
        cmd = CommandBuilder.build(
            descriptor=fastp_descriptor,
            parameters={"qualified_quality_phred": 15, "length_required": 50, "thread": 4},
            input_paths={
                "reads_1": "/data/r1.fq",
                "clean_1": "/out/c1.fq",
            },
            output_dir="/out",
            sample_id="s1",
        )
        assert "conda run -n fastp_env" in cmd

    def test_no_conda_env(self, simple_descriptor: dict) -> None:
        """没有 conda_env 时不应包装 conda run。"""
        cmd = CommandBuilder.build(
            descriptor=simple_descriptor,
            parameters={"flag": "test"},
            input_paths={"input_file": "/data/test.txt"},
            output_dir="/output",
            sample_id="s1",
        )
        assert "conda run" not in cmd

    def test_database_paths(self, kraken2_descriptor: dict) -> None:
        """数据库路径应正确注入模板上下文。"""
        cmd = CommandBuilder.build(
            descriptor=kraken2_descriptor,
            parameters={"confidence": 0.5, "threads": 4},
            input_paths={"reads": "/data/reads.fq"},
            output_dir="/out",
            sample_id="s1",
            database_paths={"db": "/databases/kraken2_standard"},
        )
        assert "--db /databases/kraken2_standard" in cmd

    def test_input_prefix_alias(self, kraken2_descriptor: dict) -> None:
        """input_paths 应同时以 name 和 input_{name} 两种方式注入上下文。"""
        cmd = CommandBuilder.build(
            descriptor=kraken2_descriptor,
            parameters={"confidence": 0.0, "threads": 8},
            input_paths={"reads": "/data/reads.fq"},
            output_dir="/out",
            sample_id="s1",
            database_paths={"db": "/db/k2"},
        )
        # 模板使用 {{ input_reads }}
        assert "/data/reads.fq" in cmd

    def test_missing_template_raises_error(self) -> None:
        """缺少 command_template 应抛出 CommandBuildError。"""
        desc = {"id": "broken", "name": "Broken"}
        with pytest.raises(CommandBuildError, match="缺少 command_template"):
            CommandBuilder.build(
                descriptor=desc,
                parameters={},
                input_paths={},
                output_dir="/out",
                sample_id="s1",
            )

    def test_jinja2_syntax_error_raises(self) -> None:
        """Jinja2 语法错误应抛出 CommandBuildError。"""
        desc = {
            "id": "bad_template",
            "command_template": "{% if unclosed %}",
        }
        with pytest.raises(CommandBuildError, match="模板渲染失败"):
            CommandBuilder.build(
                descriptor=desc,
                parameters={},
                input_paths={},
                output_dir="/out",
                sample_id="s1",
            )

    def test_sample_id_and_output_dir_in_context(self, simple_descriptor: dict) -> None:
        """sample_id 和 output_dir 应在模板上下文中可用。"""
        simple_descriptor["command_template"] = (
            "tool --out {{ output_dir }}/{{ sample_id }}.result"
        )
        cmd = CommandBuilder.build(
            descriptor=simple_descriptor,
            parameters={},
            input_paths={},
            output_dir="/project/intermediate",
            sample_id="sample_42",
        )
        assert "/project/intermediate/sample_42.result" in cmd


# ---------------------------------------------------------------------------
# merge_defaults() 测试
# ---------------------------------------------------------------------------

class TestMergeDefaults:
    """参数默认值合并测试。"""

    def test_user_overrides_default(self, fastp_descriptor: dict) -> None:
        """用户参数应覆盖默认值。"""
        merged = CommandBuilder.merge_defaults(
            fastp_descriptor, {"thread": 16}
        )
        assert merged["thread"] == 16
        assert merged["qualified_quality_phred"] == 15  # 使用默认值
        assert merged["length_required"] == 50  # 使用默认值

    def test_all_defaults(self, fastp_descriptor: dict) -> None:
        """未提供用户参数时全部使用默认值。"""
        merged = CommandBuilder.merge_defaults(fastp_descriptor, {})
        assert merged["qualified_quality_phred"] == 15
        assert merged["length_required"] == 50
        assert merged["thread"] == 4

    def test_all_user_values(self, fastp_descriptor: dict) -> None:
        """用户全部提供参数时不使用默认值。"""
        merged = CommandBuilder.merge_defaults(
            fastp_descriptor,
            {"qualified_quality_phred": 30, "length_required": 100, "thread": 16},
        )
        assert merged["qualified_quality_phred"] == 30
        assert merged["length_required"] == 100
        assert merged["thread"] == 16

    def test_extra_user_params_ignored(self, fastp_descriptor: dict) -> None:
        """用户提供的非定义参数应被忽略。"""
        merged = CommandBuilder.merge_defaults(
            fastp_descriptor, {"extra_param": "value"}
        )
        assert "extra_param" not in merged

    def test_empty_parameters(self) -> None:
        """空 parameters 定义应返回空字典。"""
        desc = {"parameters": []}
        merged = CommandBuilder.merge_defaults(desc, {"flag": "value"})
        assert merged == {}


# ---------------------------------------------------------------------------
# resolve_output_paths() 测试
# ---------------------------------------------------------------------------

class TestResolveOutputPaths:
    """输出路径解析测试。"""

    def test_fastp_outputs(self, fastp_descriptor: dict) -> None:
        """应正确解析 fastp 的输出路径。"""
        paths = CommandBuilder.resolve_output_paths(
            fastp_descriptor, "/project/intermediate/s1/fastp", "s1"
        )
        assert paths["clean_1"] == "/project/intermediate/s1/fastp/s1.clean.R1.fq.gz"
        assert paths["clean_2"] == "/project/intermediate/s1/fastp/s1.clean.R2.fq.gz"
        assert paths["report_html"] == "/project/intermediate/s1/fastp/s1.fastp.html"

    def test_empty_outputs(self) -> None:
        """没有 outputs 定义时返回空字典。"""
        paths = CommandBuilder.resolve_output_paths(
            {"outputs": []}, "/out", "s1"
        )
        assert paths == {}


# ---------------------------------------------------------------------------
# wrap() 测试
# ---------------------------------------------------------------------------

class TestWrap:
    """包装脚本生成测试。"""

    def test_wrap_contains_status_file(self) -> None:
        """包装脚本应包含 status.txt 写入。"""
        script = CommandBuilder.wrap("echo hello", "h2o_test", "/tmp/task")
        assert 'echo "RUNNING" > "$STATUS_FILE"' in script
        assert 'echo "DONE" > "$STATUS_FILE"' in script
        assert 'echo "FAILED" > "$STATUS_FILE"' in script

    def test_wrap_contains_heartbeat(self) -> None:
        """包装脚本应包含心跳机制。"""
        script = CommandBuilder.wrap("echo hello", "h2o_test", "/tmp/task")
        assert "heartbeat" in script.lower()
        assert f"sleep {HEARTBEAT_INTERVAL}" in script

    def test_wrap_contains_trap(self) -> None:
        """包装脚本应包含 trap EXIT。"""
        script = CommandBuilder.wrap("echo hello", "h2o_test", "/tmp/task")
        assert "trap _cleanup EXIT" in script

    def test_wrap_contains_user_command(self) -> None:
        """包装脚本应包含用户命令。"""
        script = CommandBuilder.wrap(
            "blastn -query /input.fa -db /db/nt",
            "h2o_blast_001",
            "/tmp/task_001",
        )
        assert "blastn -query /input.fa -db /db/nt" in script

    def test_wrap_contains_exit_code(self) -> None:
        """包装脚本应写入退出码。"""
        script = CommandBuilder.wrap("echo test", "h2o_test", "/tmp/task")
        assert "exit_code" in script.lower()

    def test_wrap_contains_log_redirect(self) -> None:
        """包装脚本应重定向日志。"""
        script = CommandBuilder.wrap("echo test", "h2o_test", "/tmp/task")
        assert "tee" in script
        assert "task.log" in script

    def test_wrap_task_dir_substitution(self) -> None:
        """包装脚本中的 task_dir 应被正确替换。"""
        script = CommandBuilder.wrap("echo", "job1", "/h2ometa/projects/p1/tasks/t1")
        assert '/h2ometa/projects/p1/tasks/t1' in script

    def test_wrap_set_strict_mode(self) -> None:
        """包装脚本应使用 set -euo pipefail。"""
        script = CommandBuilder.wrap("echo", "job1", "/tmp/t")
        assert "set -euo pipefail" in script


# ---------------------------------------------------------------------------
# conda_executable 参数测试
# ---------------------------------------------------------------------------

class TestCondaExecutable:
    """CommandBuilder.build() 的 conda_executable 参数测试。"""

    def test_conda_executable_overrides_default(self, fastp_descriptor: dict) -> None:
        """传入 conda_executable 时应使用绝对路径而非默认 "conda"。"""
        cmd = CommandBuilder.build(
            descriptor=fastp_descriptor,
            parameters={"qualified_quality_phred": 15, "length_required": 50, "thread": 4},
            input_paths={"reads_1": "/data/r1.fq", "clean_1": "/out/c1.fq"},
            output_dir="/out",
            sample_id="s1",
            conda_executable="/home/user/miniconda3/bin/conda",
        )
        assert "/home/user/miniconda3/bin/conda run -n fastp_env" in cmd
        assert "conda run -n fastp_env" in cmd

    def test_empty_conda_executable_uses_default(self, fastp_descriptor: dict) -> None:
        """空 conda_executable 应回退到 CONDA_RUNNER 默认值。"""
        cmd = CommandBuilder.build(
            descriptor=fastp_descriptor,
            parameters={"qualified_quality_phred": 15, "length_required": 50, "thread": 4},
            input_paths={"reads_1": "/data/r1.fq", "clean_1": "/out/c1.fq"},
            output_dir="/out",
            sample_id="s1",
            conda_executable="",
        )
        # 默认 CONDA_RUNNER 是 "conda"
        assert "conda run -n fastp_env" in cmd

    def test_no_conda_env_ignores_executable(self, simple_descriptor: dict) -> None:
        """没有 conda_env 时即使传了 conda_executable 也不包装。"""
        cmd = CommandBuilder.build(
            descriptor=simple_descriptor,
            parameters={"flag": "test"},
            input_paths={"input_file": "/data/test.txt"},
            output_dir="/output",
            sample_id="s1",
            conda_executable="/home/user/miniconda3/bin/conda",
        )
        assert "conda run" not in cmd
        assert "miniconda3" not in cmd
