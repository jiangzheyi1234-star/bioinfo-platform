from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_windows_api_launcher_uses_windows_owned_uv_environment() -> None:
    launcher = (REPO_ROOT / "scripts" / "run-local-api-dev.bat").read_text(encoding="utf-8")

    assert 'set "H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT=%H2OMETA_WORKDIR%\\.venv-win"' in launcher
    assert 'if not "%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"==""' in launcher
    assert 'set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"' in launcher
    assert 'set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WORKDIR%\\.venv"' not in launcher


def test_windows_launchers_preserve_explicit_uv_cache_dir() -> None:
    run_bat = (REPO_ROOT / "run.bat").read_text(encoding="utf-8")
    api_launcher = (REPO_ROOT / "scripts" / "run-local-api-dev.bat").read_text(encoding="utf-8")

    assert 'set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"' in run_bat
    assert 'set "H2OMETA_UV_CACHE_DIR=%UV_CACHE_DIR%"' in api_launcher
    assert 'set "UV_CACHE_DIR=%H2OMETA_UV_CACHE_DIR%"' in api_launcher


def test_root_launcher_defaults_artifact_cache_to_dev_cache_root() -> None:
    run_bat = (REPO_ROOT / "run.bat").read_text(encoding="utf-8")

    assert 'set "H2OMETA_ARTIFACT_CACHE_DIR=%H2OMETA_DEV_CACHE_ROOT%\\artifacts"' in run_bat


def test_root_launcher_uses_shared_release_artifact_resolver() -> None:
    run_bat = (REPO_ROOT / "run.bat").read_text(encoding="utf-8")
    resolver = (REPO_ROOT / "scripts" / "check_remote_runner_release_artifacts.py").read_text(encoding="utf-8")

    assert 'set "ARTIFACT_CHECK_ARGS=--cmd-env"' in run_bat
    assert 'scripts\\check_remote_runner_release_artifacts.py" %ARTIFACT_CHECK_ARGS%' in run_bat
    assert "--allow-staging-runner-bundle" in run_bat
    assert ":resolve_release_artifact" not in run_bat
    assert "ConvertFrom-Json" not in run_bat
    assert "RemoteRunnerArtifactProvider" in resolver
    assert "WorkflowRuntimeArtifactProvider" in resolver
    assert '"--cmd-env"' in resolver
    assert 'set "{name}={value}"' in resolver
    assert "--require-supply-chain" in resolver
    assert "--allow-staging-runner-bundle" in resolver
    assert 'scripts\\check_remote_runner_release_artifacts.py" --cmd-env --require-supply-chain' not in run_bat


def test_github_release_auth_configuration_script_is_documented() -> None:
    script = REPO_ROOT / "scripts" / "configure-github-release-auth.ps1"
    docs = (REPO_ROOT / "docs" / "local-startup.md").read_text(encoding="utf-8")
    source = script.read_text(encoding="utf-8")

    assert script.exists()
    assert "GH_CONFIG_DIR" in source
    assert "H2OMETA_GH_CONFIG_DIR" in source
    assert "auth login --hostname" in source
    assert "auth token --hostname" in source
    assert "check_remote_runner_release_artifacts.py --cmd-env" in source
    assert "configure-github-release-auth.ps1 -ValidateArtifacts" in docs


def test_root_launcher_normalizes_windows_uv_before_artifact_resolution() -> None:
    run_bat = (REPO_ROOT / "run.bat").read_text(encoding="utf-8")

    assert ":prepare_windows_uv_environment" in run_bat
    assert 'set "H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT=%REPO_ROOT%\\.venv-win"' in run_bat
    assert 'set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"' in run_bat
    assert 'set "UV_PYTHON="' in run_bat
    assert 'set "UV_PYTHON_INSTALL_DIR=%REPO_ROOT%\\.codex-uv-python"' in run_bat
    assert 'call :validate_windows_uv_project_environment' in run_bat


def test_desktop_repo_backend_uses_windows_owned_uv_environment() -> None:
    main_rs = (REPO_ROOT / "apps" / "desktop" / "src-tauri" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )

    assert 'const DEFAULT_WINDOWS_UV_ENV_DIR: &str = ".venv-win";' in main_rs
    assert 'env::var("H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT")' in main_rs
    assert 'workdir.join(DEFAULT_WINDOWS_UV_ENV_DIR)' in main_rs
    assert '.env("UV_PROJECT_ENVIRONMENT", workdir.join(".venv"))' not in main_rs


def test_hidden_web_stack_launcher_normalizes_duplicate_path_environment() -> None:
    launcher = (REPO_ROOT / "scripts" / "start-web-stack-hidden.ps1").read_text(encoding="utf-8")

    assert "function Repair-ProcessPathEnvironment" in launcher
    assert '[StringComparison]::OrdinalIgnoreCase' in launcher
    assert 'SetEnvironmentVariable("Path", $pathValue, "Process")' in launcher
    assert "Repair-ProcessPathEnvironment" in launcher


def test_stop_existing_local_api_treats_transient_listener_pid_as_nonfatal() -> None:
    helper = (REPO_ROOT / "scripts" / "stop-existing-local-api.ps1").read_text(encoding="utf-8")

    assert "catch [Microsoft.PowerShell.Commands.ProcessCommandException]" in helper
    assert "exited before stop" in helper
    assert "is no longer listening" in helper
