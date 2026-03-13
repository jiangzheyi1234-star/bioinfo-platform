"""container_detector 命令构造安全性测试。"""

from core.environment import container_detector as cd


def test_pull_singularity_image_quotes_user_inputs() -> None:
    calls: list[str] = []

    def ssh_run(cmd: str, timeout: int):
        calls.append(cmd)
        return (0, "", "")

    ok, msg = cd.pull_singularity_image(
        ssh_run_fn=ssh_run,
        image_uri="docker://repo/img:1.0; touch /tmp/pwn",
        cache_dir="~/cache dir",
        output_name="out;rm -rf /",
    )

    assert ok is True
    assert "touch /tmp/pwn" in calls[0]
    assert "mkdir -p $HOME/'cache dir'" in calls[0]
    assert "singularity pull --force --name $HOME/'cache dir/out;rm -rf /.sif'" in calls[0]
    assert "'docker://repo/img:1.0; touch /tmp/pwn'" in calls[0]
    assert msg == "~/cache dir/out;rm -rf /.sif"


def test_pull_docker_image_quotes_image_name() -> None:
    calls: list[str] = []

    def ssh_run(cmd: str, timeout: int):
        calls.append(cmd)
        return (0, "", "")

    ok, _ = cd.pull_docker_image(
        ssh_run_fn=ssh_run,
        image="repo/image:latest; echo hacked",
    )

    assert ok is True
    assert calls[0] == "docker pull 'repo/image:latest; echo hacked'"


def test_remove_singularity_image_uses_double_dash() -> None:
    calls: list[str] = []

    def ssh_run(cmd: str, timeout: int):
        calls.append(cmd)
        return (0, "", "")

    ok, _ = cd.remove_singularity_image(
        ssh_run_fn=ssh_run,
        image_path="-rf /",
    )

    assert ok is True
    assert calls[0] == "rm -f -- '-rf /'"


def test_build_docker_exec_command_quotes_and_wraps_with_sh_lc() -> None:
    cmd = cd.build_docker_exec_command(
        image="repo/xx:1.0",
        command="echo ok; touch /tmp/pwn",
        binds=["/a b:/x y"],
        workdir="/work dir",
        rm=True,
        interactive=False,
    )
    assert cmd == (
        "docker run --rm -v '/a b:/x y' -w '/work dir' "
        "repo/xx:1.0 sh -lc 'echo ok; touch /tmp/pwn'"
    )


def test_build_singularity_exec_command_quotes_and_wraps_with_sh_lc() -> None:
    cmd = cd.build_singularity_exec_command(
        image_path="/path with space/img.sif",
        command="echo ok; id",
        binds=["/h:/c"],
        workdir="/wk dir",
    )
    assert cmd == (
        "singularity exec --bind /h:/c --pwd '/wk dir' "
        "'/path with space/img.sif' sh -lc 'echo ok; id'"
    )
