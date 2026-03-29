"""环境检测与安装模块测试 — 合并自 test_env_detector.py + test_env_installer.py"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from core.environment.env_detector import (
    CondaStatus,
    detect,
    expected_env_path,
    infer_conda_root,
    install_miniforge,
    pin_create_env_to_conda_root,
    rewrite_install_cmd,
)
from core.environment.env_batch_checker import check_all_envs, get_existing_env_paths
from core.environment.env_installer import EnvInstaller, INSTALL_BASE
from core.environment.h2o_env_paths import H2O_CONDA_EXE, H2O_CONDA_HOME, H2O_CONDARC
from core.environment.miniforge_condarc import (
    CONDARC_TEMPLATE,
    MANAGED_OVERRIDE_CHANNEL_URLS,
    build_override_channel_args,
)
from core.environment.miniforge_release import (
    MINIFORGE_RELEASE_API_URL,
    build_miniforge_download_candidates,
)
from core.remote.server_capabilities import ServerCapabilities


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def make_ssh_fn(responses: dict):
    """创建模拟 ssh_run_fn，根据命令返回预设结果。"""
    calls = []
    def fn(cmd, timeout=15):
        calls.append(cmd)
        if cmd in responses:
            return responses[cmd]
        for key, val in responses.items():
            if cmd.startswith(key):
                return val
        return (1, "", "command not found")
    fn.calls = calls
    return fn


# ----------------------------------------------------------------------------
# detect() 检测测试
# ----------------------------------------------------------------------------

class TestDetect:
    """env_detector.detect() 检测测试 — 精简核心场景"""

    def test_managed_conda_success(self):
        """固定自管路径存在时返回 OK。"""
        fn = make_ssh_fn({
            "bash -c '$HOME/.h2ometa/conda/bin/conda --version'": (0, "conda 24.3.0", ""),
            "eval echo $HOME/.h2ometa/conda/bin/conda": (0, "/home/user/.h2ometa/conda/bin/conda", ""),
        })
        result = detect(fn)
        assert result.status == CondaStatus.OK
        assert result.executable == "/home/user/.h2ometa/conda/bin/conda"

    def test_all_not_found(self):
        """全部未命中 → NOT_FOUND。"""
        fn = make_ssh_fn({})
        result = detect(fn)
        assert result.status == CondaStatus.NOT_FOUND
        assert result.executable is None


# ----------------------------------------------------------------------------
# install_miniforge() 测试
# ----------------------------------------------------------------------------

class TestInstallMiniforge:
    """Miniforge 安装测试"""

    @staticmethod
    def _caps(**overrides) -> ServerCapabilities:
        data = {
            "arch": "x86_64",
            "has_curl": True,
            "has_wget": False,
            "has_screen": True,
            "has_sha256sum": True,
            "free_disk_gb": 20.0,
        }
        data.update(overrides)
        return ServerCapabilities(**data)

    def test_install_success(self):
        """Miniforge 安装成功流程。"""
        calls = []
        release_tag = "25.1.0-0"
        installer_path = "/tmp/miniforge_install.abcd12.sh"
        checksum_path = "/tmp/miniforge_install.abcd12.sha256"
        candidate = build_miniforge_download_candidates(release_tag, "x86_64")[-1]
        expected_sha = "a" * 64

        def fn(cmd, timeout=15):
            calls.append(cmd)
            if cmd == "mktemp /tmp/miniforge_install.XXXXXX.sh":
                return 0, f"{installer_path}\n", ""
            if cmd == "mktemp /tmp/miniforge_install.XXXXXX.sha256":
                return 0, f"{checksum_path}\n", ""
            if cmd.startswith("rm -f "):
                return 0, "", ""
            if cmd == f"curl -fsSL --connect-timeout 15 --max-time 60 {MINIFORGE_RELEASE_API_URL}":
                return 0, f'{{"tag_name":"{release_tag}"}}', ""
            if cmd == f"curl -fsSL --connect-timeout 15 --max-time 120 -o {installer_path} {candidate.installer_url}":
                return 0, "", ""
            if cmd == f"stat -c%s {installer_path}":
                return 0, "1500000\n", ""
            if cmd == f"head -n 1 {installer_path}":
                return 0, "#!/bin/bash\n", ""
            if cmd == f"curl -fsSL --connect-timeout 15 --max-time 120 -o {checksum_path} {candidate.sha256_url}":
                return 0, "", ""
            if cmd == f"cat {checksum_path}":
                return 0, f"{expected_sha}  Miniforge3-Linux-x86_64.sh\n", ""
            if cmd == f"printf '%s  %s\\n' {expected_sha} {installer_path} | sha256sum -c -":
                return 0, f"{installer_path}: OK\n", ""
            if cmd == f"bash {installer_path} -b -p \"$(eval echo {H2O_CONDA_HOME})\"":
                return 0, "", ""
            if cmd == "bash -c '$HOME/.h2ometa/conda/bin/conda --version'":
                return 0, "conda 24.7.1", ""
            if cmd == "eval echo $HOME/.h2ometa/conda/bin/conda":
                return 0, "/home/user/.h2ometa/conda/bin/conda", ""
            if cmd == "mkdir -p ~/.h2ometa/runtime":
                return 0, "", ""
            if cmd.startswith("echo '") and f"> {H2O_CONDARC}" in cmd:
                return 0, "", ""
            return 1, "", f"unexpected command: {cmd}"

        result = install_miniforge(fn, self._caps())
        assert result.status == CondaStatus.OK
        assert any(f"/releases/download/{release_tag}/Miniforge3-Linux-x86_64.sh" in cmd for cmd in calls)
        assert any(candidate.sha256_url in cmd for cmd in calls)
        assert "uname -m" not in calls
        assert "command -v curl" not in calls
        assert "command -v wget" not in calls
        assert not any("config --add channels bioconda" in cmd for cmd in calls)
        assert not any("config --set channel_priority" in cmd for cmd in calls)

    def test_install_fails_on_unsupported_arch(self):
        """不支持的架构应失败。"""
        fn = make_ssh_fn({})
        result = install_miniforge(fn, self._caps(arch="armv7l"))
        assert result.status == CondaStatus.NOT_FOUND
        assert "不支持的架构" in result.message

    def test_install_reports_per_source_failures(self):
        release_tag = "25.1.0-0"
        installer_path = "/tmp/miniforge_install.abcd12.sh"
        checksum_path = "/tmp/miniforge_install.abcd12.sha256"
        candidates = build_miniforge_download_candidates(release_tag, "x86_64")

        def fn(cmd, timeout=15):
            if cmd == "mktemp /tmp/miniforge_install.XXXXXX.sh":
                return 0, f"{installer_path}\n", ""
            if cmd == "mktemp /tmp/miniforge_install.XXXXXX.sha256":
                return 0, f"{checksum_path}\n", ""
            if cmd.startswith("rm -f "):
                return 0, "", ""
            if cmd == f"curl -fsSL --connect-timeout 15 --max-time 60 {MINIFORGE_RELEASE_API_URL}":
                return 0, f'{{"tag_name":"{release_tag}"}}', ""
            for candidate in candidates:
                if cmd == f"curl -fsSL --connect-timeout 15 --max-time 120 -o {installer_path} {candidate.installer_url}":
                    return 1, "", f"{candidate.label} down"
            return 1, "", f"unexpected command: {cmd}"

        result = install_miniforge(fn, self._caps())
        assert result.status == CondaStatus.NOT_FOUND
        assert "[tsinghua] installer download failed" in result.message
        assert "[github] installer download failed" in result.message


def test_shared_condarc_template_matches_runtime_expectations():
    assert "channels:" in CONDARC_TEMPLATE
    assert "  - conda-forge" in CONDARC_TEMPLATE
    assert "  - bioconda" in CONDARC_TEMPLATE
    assert "default_channels:" in CONDARC_TEMPLATE
    assert "custom_channels:" in CONDARC_TEMPLATE
    assert "channel_priority: strict" in CONDARC_TEMPLATE
    assert "solver: libmamba" in CONDARC_TEMPLATE
    assert "show_channel_urls: true" in CONDARC_TEMPLATE
    assert "auto_activate_base: false" in CONDARC_TEMPLATE
    assert "mirrors.tuna.tsinghua.edu.cn/anaconda/cloud" in CONDARC_TEMPLATE
    assert "mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main" in CONDARC_TEMPLATE


def test_build_override_channel_args_uses_managed_mirror_urls():
    args = build_override_channel_args()
    assert args[0] == "--override-channels"
    urls = [args[i + 1] for i, tok in enumerate(args) if tok == "-c"]
    assert urls == list(MANAGED_OVERRIDE_CHANNEL_URLS)
    assert len(urls) == len(MANAGED_OVERRIDE_CHANNEL_URLS)


# ----------------------------------------------------------------------------
# rewrite_install_cmd() 测试
# ----------------------------------------------------------------------------

class TestRewriteInstallCmd:
    """命令替换测试"""

    def test_basic_rewrite(self):
        result = rewrite_install_cmd(
            "conda create -n fastp_env fastp -y",
            "/home/user/miniconda3/bin/conda")
        assert "/home/user/miniconda3/bin/conda create" in result

    def test_non_conda_cmd_unchanged(self):
        result = rewrite_install_cmd("pip install fastp", "/home/user/conda/bin/conda")
        assert result == "pip install fastp"


# ----------------------------------------------------------------------------
# Conda Root Helpers 测试
# ----------------------------------------------------------------------------

class TestCondaRootHelpers:
    """conda 路径辅助函数测试"""

    def test_infer_conda_root(self):
        assert infer_conda_root("/home/user/anaconda3/bin/conda") == "/home/user/anaconda3"
        assert infer_conda_root("") == ""

    def test_expected_env_path(self):
        assert expected_env_path("/opt/miniconda3/bin/conda", "fastp_env") == "~/.h2ometa/conda/envs/fastp_env"

    def test_pin_create_env_to_conda_root(self):
        cmd = "/opt/conda/bin/conda create -n fastp_env fastp -y"
        pinned = pin_create_env_to_conda_root(cmd, "/opt/conda/bin/conda")
        assert " -p /opt/conda/envs/fastp_env " in f" {pinned} "


# ----------------------------------------------------------------------------
# EnvInstaller 测试
# ----------------------------------------------------------------------------

class TestEnvInstallerSubmit:
    """EnvInstaller.submit() 测试"""

    def test_submit_basic(self):
        """基本提交流程。"""
        fn = make_ssh_fn({
            "mkdir -p ~/.h2ometa/runtime": (0, "", ""),
            "echo '": (0, "", ""),
            "eval echo $HOME/.h2ometa/conda/bin/conda": (
                0, "/home/user/.h2ometa/conda/bin/conda\n", ""
            ),
            "eval echo $HOME/.h2ometa/conda/envs/fastp_env.installing": (
                0, "/home/user/.h2ometa/conda/envs/fastp_env.installing\n", ""
            ),
            "mkdir -p": (0, "", ""),
            "screen -S h2o_install_fastp -X quit": (0, "", ""),
            "screen -dmS": (0, "", ""),
        })
        result = EnvInstaller.submit(
            fn, "fastp",
            "conda create -n fastp_env fastp -y",
            "/home/user/.h2ometa/conda/bin/conda")
        assert result["job_id"] == "h2o_install_fastp"
        assert result["task_dir"] == f"{INSTALL_BASE}/fastp"

    def test_submit_rewrites_conda_path(self):
        """提交时替换 conda 路径。"""
        written_script = []
        def capture_fn(cmd, timeout=15):
            if cmd == "mkdir -p ~/.h2ometa/runtime":
                return (0, "", "")
            if cmd.startswith("eval echo $HOME/.h2ometa/conda/bin/conda"):
                return (0, "/home/user/.h2ometa/conda/bin/conda\n", "")
            if cmd.startswith("eval echo $HOME/.h2ometa/conda/envs/fastp_env.installing"):
                return (0, "/home/user/.h2ometa/conda/envs/fastp_env.installing\n", "")
            if cmd.startswith("echo '") and f"> {H2O_CONDARC}" in cmd:
                return (0, "", "")
            if cmd.startswith("echo '"):
                parts = cmd.split("'")
                if len(parts) >= 2:
                    try:
                        decoded = base64.b64decode(parts[1]).decode()
                        written_script.append(decoded)
                    except Exception:
                        pass
            return (0, "", "")

        EnvInstaller.submit(
            capture_fn,
            "fastp",
            "conda create -n fastp_env -y",
            "/home/user/.h2ometa/conda/bin/conda",
        )
        assert len(written_script) == 1
        assert "/home/user/.h2ometa/conda/bin/conda create" in written_script[0]
        assert "--override-channels" in written_script[0]
        assert "mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge" in written_script[0]
        assert "mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main" in written_script[0]

    def test_submit_expands_tilde_conda_executable_before_writing_script(self):
        """提交时先将自管 conda 的 ~ 路径展开为远端绝对路径。"""
        written_script = []

        def capture_fn(cmd, timeout=15):
            if cmd == "mkdir -p ~/.h2ometa/runtime":
                return (0, "", "")
            if cmd == "eval echo $HOME/.h2ometa/conda/bin/conda":
                return (0, "/home/user/.h2ometa/conda/bin/conda\n", "")
            if cmd == "eval echo $HOME/.h2ometa/conda/envs/fastp_env.installing":
                return (0, "/home/user/.h2ometa/conda/envs/fastp_env.installing\n", "")
            if cmd.startswith("echo '") and f"> {H2O_CONDARC}" in cmd:
                return (0, "", "")
            if cmd.startswith("echo '"):
                parts = cmd.split("'")
                if len(parts) >= 2:
                    written_script.append(base64.b64decode(parts[1]).decode())
                return (0, "", "")
            if cmd.startswith("mkdir -p") or cmd.startswith("screen -S") or cmd.startswith("screen -dmS"):
                return (0, "", "")
            return (1, "", f"unexpected cmd: {cmd}")

        EnvInstaller.submit(
            capture_fn,
            "fastp",
            "conda create -n fastp_env -y",
            H2O_CONDA_EXE,
            verify_cmd="fastp --version",
            version_regex=r"\\d+\\.\\d+",
        )

        assert len(written_script) == 1
        script = written_script[0]
        assert "/home/user/.h2ometa/conda/bin/conda create" in script
        assert "/home/user/.h2ometa/conda/bin/conda run -p \"$TMP_PREFIX\"" in script
        assert "'~/.h2ometa/conda/bin/conda'" not in script
        assert "--override-channels" in script

    def test_submit_rejects_composite_install_cmd(self):
        fn = make_ssh_fn({
            "mkdir -p ~/.h2ometa/runtime": (0, "", ""),
            "echo '": (0, "", ""),
            "eval echo $HOME/.h2ometa/conda/bin/conda": (
                0, "/home/user/.h2ometa/conda/bin/conda\n", ""
            ),
        })

        with pytest.raises(RuntimeError, match="复合 shell 语法"):
            EnvInstaller.submit(
                fn,
                "fastp",
                "conda create -n fastp_env -y && echo done",
                H2O_CONDA_EXE,
            )

    def test_submit_requires_conda_executable(self):
        fn = make_ssh_fn({})
        with pytest.raises(RuntimeError, match="未检测到 conda 可执行路径"):
            EnvInstaller.submit(
                fn,
                "fastp",
                "conda create -n fastp_env -y",
                "",
            )

    def test_submit_rejects_non_managed_conda_executable(self):
        fn = make_ssh_fn({})
        with pytest.raises(RuntimeError, match="检测到非自管 conda 路径"):
            EnvInstaller.submit(
                fn,
                "fastp",
                "conda create -n fastp_env -y",
                "/opt/conda/bin/conda",
            )


class TestBatchChecker:
    def test_check_all_envs_only_accepts_h2o_envs_dir(self):
        fn = make_ssh_fn({
            "/home/user/.h2ometa/conda/bin/conda env list --json": (
                0,
                '{"envs":["/home/user/anaconda3/envs/fastp_env","/home/user/.h2ometa/conda/envs/fastp_env","/home/user/.h2ometa/conda/envs/kraken2_env"]}',
                "",
            ),
            "eval echo ~/.h2ometa/conda/envs": (0, "/home/user/.h2ometa/conda/envs\n", ""),
            "eval echo ~/.h2ometa/conda/envs/fastp_env": (0, "/home/user/.h2ometa/conda/envs/fastp_env\n", ""),
            "eval echo ~/.h2ometa/conda/envs/kraken2_env": (0, "/home/user/.h2ometa/conda/envs/kraken2_env\n", ""),
        })

        results, envs = check_all_envs(
            ssh_run_fn=fn,
            tools=[
                {"id": "fastp", "conda_env": "fastp_env"},
                {"id": "kraken2", "conda_env": "kraken2_env"},
            ],
            conda_executable="/home/user/.h2ometa/conda/bin/conda",
        )

        assert set(envs) == {
            "/home/user/.h2ometa/conda/envs/fastp_env",
            "/home/user/.h2ometa/conda/envs/kraken2_env",
        }
        assert {r.tool_id: r.ok for r in results} == {"fastp": True, "kraken2": True}

    def test_get_existing_env_paths_filters_legacy_paths(self):
        fn = make_ssh_fn({
            "/home/user/.h2ometa/conda/bin/conda env list --json": (
                0,
                '{"envs":["/home/user/anaconda3/envs/fastp_env","/home/user/.h2ometa/conda/envs/fastp_env"]}',
                "",
            ),
            "eval echo ~/.h2ometa/conda/envs": (0, "/home/user/.h2ometa/conda/envs\n", ""),
        })
        paths = get_existing_env_paths(fn, "/home/user/.h2ometa/conda/bin/conda")
        assert paths == {"/home/user/.h2ometa/conda/envs/fastp_env"}

    def test_check_all_envs_rejects_non_managed_conda(self):
        fn = make_ssh_fn({
            "/opt/conda/bin/conda env list --json": (
                0, '{"envs":["/opt/conda/envs/fastp_env"]}', ""
            )
        })
        results, envs = check_all_envs(
            ssh_run_fn=fn,
            tools=[
                {"id": "fastp", "conda_env": "fastp_env"},
                {"id": "unknown", "conda_env": ""},
            ],
            conda_executable="/opt/conda/bin/conda",
        )
        assert envs == []
        assert {r.tool_id: r.ok for r in results} == {"fastp": False, "unknown": True}

    def test_check_all_envs_expands_h2o_base_only_once(self):
        fn = make_ssh_fn({
            "/home/user/.h2ometa/conda/bin/conda env list --json": (
                0,
                '{"envs":["/home/user/.h2ometa/conda/envs/fastp_env","/home/user/.h2ometa/conda/envs/kraken2_env"]}',
                "",
            ),
            "eval echo ~/.h2ometa/conda/envs": (0, "/home/user/.h2ometa/conda/envs\n", ""),
        })

        results, _envs = check_all_envs(
            ssh_run_fn=fn,
            tools=[
                {"id": "fastp", "conda_env": "fastp_env"},
                {"id": "kraken2", "conda_env": "kraken2_env"},
            ],
            conda_executable="/home/user/.h2ometa/conda/bin/conda",
        )
        assert {r.tool_id: r.ok for r in results} == {"fastp": True, "kraken2": True}
        eval_calls = [c for c in fn.calls if c.startswith("eval echo ")]
        assert eval_calls == ["eval echo ~/.h2ometa/conda/envs"]


class TestEnvInstallerBatchProbe:
    def test_batch_probe_parses_rows(self):
        log_text = "Downloading... 32%\nSpeed 3.2MB/s"
        line1 = "\t".join(
            [
                "fastp",
                "RUNNING",
                "",
                "1",
                "12345",
                base64.b64encode(log_text.encode("utf-8")).decode("ascii"),
            ]
        )
        line2 = "\t".join(["abricate", "DONE", "0", "0", "0", ""])
        payload = f"{line1}\n{line2}\n"

        def fn(cmd, timeout=20):
            if 'for TOOL_ID in' in cmd:
                return 0, payload, ""
            return 1, "", "unexpected"

        rows = EnvInstaller.batch_probe(fn, ["fastp", "abricate"], tail_lines=80, timeout=20)
        assert len(rows) == 2
        assert rows[0]["tool_id"] == "fastp"
        assert rows[0]["status"] == "RUNNING"
        assert rows[0]["session_alive"] is True
        assert rows[0]["log_size"] == 12345
        assert "3.2MB/s" in rows[0]["log_text"]
        assert rows[1]["tool_id"] == "abricate"
        assert rows[1]["status"] == "DONE"
        assert rows[1]["exit_code"] == "0"
