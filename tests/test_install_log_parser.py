from __future__ import annotations

from ui.install_log_parser import analyze_install_log, build_failure_guidance, extract_progress_and_speed


def test_extract_progress_and_speed_from_raw_log():
    progress, speed = extract_progress_and_speed("Downloading foo.tar.bz2 73% 2.4MB/s")

    assert progress == "73%"
    assert speed == "2.4MB/s"


def test_analyze_install_log_detects_resolving_phase():
    analysis = analyze_install_log(
        "RUNNING",
        log_text="Collecting package metadata (current_repodata.json): done\nSolving environment: done",
    )

    assert analysis.phase == "resolving"
    assert analysis.phase_text == "正在解析依赖"
    assert analysis.is_progress_indeterminate is True


def test_analyze_install_log_detects_downloading_phase():
    analysis = analyze_install_log(
        "RUNNING",
        log_text="Downloading and Extracting Packages:\npython-3.11 73% 2.1MB/s",
    )

    assert analysis.phase == "downloading"
    assert analysis.phase_text == "正在下载依赖包"
    assert analysis.progress_value == 73
    assert analysis.speed_text == "2.1MB/s"


def test_analyze_install_log_detects_installing_phase():
    analysis = analyze_install_log(
        "RUNNING",
        log_text="Downloading packages...\nExecuting transaction: done\npost-link script running",
    )

    assert analysis.phase == "installing"
    assert analysis.phase_text == "正在安装软件包"


def test_analyze_install_log_defaults_to_resolving_when_no_keywords():
    analysis = analyze_install_log("RUNNING", log_text="environment creation has started")

    assert analysis.phase == "resolving"
    assert analysis.phase_text == "正在解析依赖"


def test_build_failure_guidance_includes_exit_code():
    guidance = build_failure_guidance("17")

    assert "排查建议" in guidance
    assert "exit_code: 17" in guidance
