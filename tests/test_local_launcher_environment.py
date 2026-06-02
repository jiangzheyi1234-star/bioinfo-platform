from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_windows_api_launcher_uses_windows_owned_uv_environment() -> None:
    launcher = (REPO_ROOT / "scripts" / "run-local-api-dev.bat").read_text(encoding="utf-8")

    assert 'set "H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT=%H2OMETA_WORKDIR%\\.venv-win"' in launcher
    assert 'if not "%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"==""' in launcher
    assert 'set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT%"' in launcher
    assert 'set "UV_PROJECT_ENVIRONMENT=%H2OMETA_WORKDIR%\\.venv"' not in launcher


def test_desktop_repo_backend_uses_windows_owned_uv_environment() -> None:
    main_rs = (REPO_ROOT / "apps" / "desktop" / "src-tauri" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )

    assert 'const DEFAULT_WINDOWS_UV_ENV_DIR: &str = ".venv-win";' in main_rs
    assert 'env::var("H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT")' in main_rs
    assert 'workdir.join(DEFAULT_WINDOWS_UV_ENV_DIR)' in main_rs
    assert '.env("UV_PROJECT_ENVIRONMENT", workdir.join(".venv"))' not in main_rs
