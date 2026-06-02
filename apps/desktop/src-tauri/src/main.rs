#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use std::{env, net::TcpStream, thread};
use tauri::Manager;

const TERMINAL_RUNTIME_BUILD_ID: &str = "terminal-websocket-v1";
const DEFAULT_WINDOWS_UV_ENV_DIR: &str = ".venv-win";

struct BackendState(Mutex<Option<Child>>);

struct PythonCommand {
    program: String,
    args: Vec<String>,
}

struct BackendCommand {
    program: String,
    args: Vec<String>,
    workdir: Option<PathBuf>,
    source: String,
}

struct SpawnedBackend {
    child: Child,
    log_path: PathBuf,
}

fn terminate_backend_child(child: &mut Child) {
    #[cfg(windows)]
    {
        let pid = child.id();
        let status = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if status.map(|value| value.success()).unwrap_or(false) {
            let _ = child.wait();
            return;
        }
    }

    let _ = child.kill();
    let _ = child.wait();
}

fn candidate_python_commands() -> Vec<PythonCommand> {
    let mut commands = vec![PythonCommand {
        program: "uv".to_string(),
        args: vec![
            "run".to_string(),
            "--frozen".to_string(),
            "python".to_string(),
        ],
    }];

    if let Ok(explicit) = std::env::var("H2OMETA_PYTHON") {
        if !explicit.trim().is_empty() {
            commands.insert(
                0,
                PythonCommand {
                    program: explicit,
                    args: vec![],
                },
            );
        }
    }

    if cfg!(windows) {
        return commands;
    }

    commands.extend(vec![
        PythonCommand {
            program: "python3".to_string(),
            args: vec![],
        },
        PythonCommand {
            program: "python".to_string(),
            args: vec![],
        },
    ]);
    commands
}

fn has_backend_entry(path: &Path) -> bool {
    path.join("apps").join("api").join("run.py").exists()
}

fn locate_repo_root_from(start: &Path) -> Option<PathBuf> {
    let mut cursor = Some(start);
    while let Some(path) = cursor {
        if has_backend_entry(path) {
            return Some(path.to_path_buf());
        }
        cursor = path.parent();
    }
    None
}

fn repo_backend_workdir() -> Result<PathBuf, String> {
    if let Ok(explicit) = std::env::var("H2OMETA_WORKDIR") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            let path = PathBuf::from(trimmed);
            if has_backend_entry(&path) {
                return Ok(path);
            }
            return Err(format!(
                "H2OMETA_WORKDIR does not point to repo root with apps/api/run.py: {}",
                path.display()
            ));
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        if let Some(root) = locate_repo_root_from(&cwd) {
            return Ok(root);
        }
    }

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if let Some(root) = locate_repo_root_from(exe_dir) {
                return Ok(root);
            }
        }
    }

    Err("cannot locate backend workdir; set H2OMETA_WORKDIR to repo root".to_string())
}

fn explicit_backend_command() -> Result<Option<BackendCommand>, String> {
    let program = env::var("H2OMETA_BACKEND_EXE").unwrap_or_default();
    if program.trim().is_empty() {
        return Ok(None);
    }
    let workdir = env::var("H2OMETA_BACKEND_CWD").ok().and_then(|value| {
        let trimmed = value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(PathBuf::from(trimmed))
        }
    });
    Ok(Some(BackendCommand {
        program,
        args: vec![],
        workdir,
        source: "explicit".to_string(),
    }))
}

fn sibling_sidecar_command() -> Result<Option<BackendCommand>, String> {
    let exe_path =
        env::current_exe().map_err(|err| format!("resolve current exe failed: {}", err))?;
    let exe_dir = exe_path
        .parent()
        .ok_or_else(|| format!("cannot resolve parent dir for {}", exe_path.display()))?;
    let binary_name = if cfg!(windows) {
        "h2ometa-api.exe"
    } else {
        "h2ometa-api"
    };
    let candidate = exe_dir.join(binary_name);
    if !candidate.exists() {
        return Ok(None);
    }
    Ok(Some(BackendCommand {
        program: candidate.display().to_string(),
        args: vec![],
        workdir: candidate.parent().map(|path| path.to_path_buf()),
        source: "sidecar".to_string(),
    }))
}

fn repo_backend_fallback_setting() -> Option<bool> {
    env::var("H2OMETA_ALLOW_REPO_BACKEND")
        .ok()
        .and_then(|value| match value.trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "yes" | "on" => Some(true),
            "0" | "false" | "no" | "off" => Some(false),
            _ => None,
        })
}

fn dev_repo_backend_command() -> Result<Option<BackendCommand>, String> {
    let explicit_setting = repo_backend_fallback_setting();
    let allow_repo_backend = explicit_setting.unwrap_or(cfg!(debug_assertions) || cfg!(windows));
    if !allow_repo_backend {
        return Ok(None);
    }
    let workdir = match repo_backend_workdir() {
        Ok(path) => path,
        Err(err) => {
            if explicit_setting == Some(true) {
                return Err(err);
            }
            return Ok(None);
        }
    };
    Ok(Some(BackendCommand {
        program: String::new(),
        args: vec![],
        workdir: Some(workdir),
        source: "repo".to_string(),
    }))
}

fn backend_log_path(workdir: Option<&Path>) -> Result<PathBuf, String> {
    if let Some(path) = workdir {
        let logs_dir = path.join("logs");
        let _ = std::fs::create_dir_all(&logs_dir);
        return Ok(logs_dir.join("desktop_backend_boot.log"));
    }

    let temp_logs = env::temp_dir().join("h2ometa-desktop");
    std::fs::create_dir_all(&temp_logs)
        .map_err(|err| format!("create temp log dir failed: {}", err))?;
    Ok(temp_logs.join("desktop_backend_boot.log"))
}

fn repo_uv_cache_dir(workdir: &Path) -> PathBuf {
    if let Ok(explicit) = env::var("H2OMETA_UV_CACHE_DIR") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    if let Ok(explicit) = env::var("UV_CACHE_DIR") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    if cfg!(windows) {
        if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
            let trimmed = local_app_data.trim();
            if !trimmed.is_empty() {
                return PathBuf::from(trimmed)
                    .join("H2OMeta")
                    .join("dev-cache")
                    .join("uv-cache");
            }
        }
    }

    if let Ok(home) = env::var("HOME") {
        let trimmed = home.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed)
                .join(".cache")
                .join("h2ometa")
                .join("uv-cache");
        }
    }

    workdir.join(".uv-cache")
}

fn repo_uv_project_environment(workdir: &Path) -> PathBuf {
    if let Ok(explicit) = env::var("H2OMETA_WINDOWS_UV_PROJECT_ENVIRONMENT") {
        let trimmed = explicit.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }

    if cfg!(windows) {
        return workdir.join(DEFAULT_WINDOWS_UV_ENV_DIR);
    }

    workdir.join(".venv")
}

fn spawn_explicit_backend(cmd_spec: BackendCommand) -> Result<SpawnedBackend, String> {
    let log_path = backend_log_path(cmd_spec.workdir.as_deref())?;
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|err| format!("open backend log failed: {}", err))?;
    let log_file_err = log_file
        .try_clone()
        .map_err(|err| format!("clone backend log handle failed: {}", err))?;

    let mut cmd = Command::new(&cmd_spec.program);
    cmd.args(cmd_spec.args.iter())
        .env("H2OMETA_RUNTIME_BUILD_ID", TERMINAL_RUNTIME_BUILD_ID)
        .env("H2OMETA_BACKEND_SOURCE", &cmd_spec.source)
        .env("WSL_UTF8", "1")
        .env("PYTHONUTF8", "1")
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_file_err));
    if let Some(workdir) = &cmd_spec.workdir {
        cmd.current_dir(workdir);
    }

    let child = cmd
        .spawn()
        .map_err(|err| format!("spawn backend failed with {}: {}", cmd_spec.program, err))?;
    Ok(SpawnedBackend { child, log_path })
}

fn spawn_repo_backend(workdir: PathBuf) -> Result<SpawnedBackend, String> {
    let log_path = backend_log_path(Some(&workdir))?;
    let mut last_error = String::from("no python command available");

    for cmd_spec in candidate_python_commands() {
        let log_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|err| format!("open backend log failed: {}", err))?;
        let log_file_err = log_file
            .try_clone()
            .map_err(|err| format!("clone backend log handle failed: {}", err))?;

        let mut cmd = Command::new(&cmd_spec.program);
        let uv_cache_dir = repo_uv_cache_dir(&workdir);
        let uv_project_environment = repo_uv_project_environment(&workdir);
        let _ = std::fs::create_dir_all(&uv_cache_dir);
        cmd.args(cmd_spec.args.iter())
            .arg("-m")
            .arg("apps.api.run")
            .current_dir(&workdir)
            .env("H2OMETA_RUNTIME_BUILD_ID", TERMINAL_RUNTIME_BUILD_ID)
            .env("H2OMETA_BACKEND_SOURCE", "repo")
            .env("UV_CACHE_DIR", uv_cache_dir)
            .env("UV_PROJECT_ENVIRONMENT", uv_project_environment)
            .env("UV_PYTHON_INSTALL_DIR", workdir.join(".codex-uv-python"))
            .env_remove("UV_PYTHON")
            .env("WSL_UTF8", "1")
            .env("PYTHONUTF8", "1")
            .stdout(Stdio::from(log_file))
            .stderr(Stdio::from(log_file_err));

        match cmd.spawn() {
            Ok(child) => return Ok(SpawnedBackend { child, log_path }),
            Err(err) => {
                last_error = format!("spawn backend failed with {}: {}", cmd_spec.program, err);
            }
        }
    }
    Err(last_error)
}

fn spawn_backend() -> Result<SpawnedBackend, String> {
    if let Some(command) = explicit_backend_command()? {
        return spawn_explicit_backend(command);
    }
    if let Some(command) = sibling_sidecar_command()? {
        return spawn_explicit_backend(command);
    }
    if let Some(command) = dev_repo_backend_command()? {
        let workdir = command
            .workdir
            .ok_or_else(|| "repo backend command is missing workdir".to_string())?;
        return spawn_repo_backend(workdir);
    }
    Err(
        "no desktop backend launch target configured; set H2OMETA_BACKEND_EXE, bundle a sibling h2ometa-api sidecar, or run a debug/dev desktop build from the repo root (auto repo-backend fallback) / opt into fallback explicitly with H2OMETA_ALLOW_REPO_BACKEND=1".to_string(),
    )
}

fn read_log_tail(log_path: &Path, max_chars: usize) -> String {
    let content = std::fs::read_to_string(log_path).unwrap_or_else(|_| String::new());
    if content.chars().count() <= max_chars {
        return content;
    }
    content
        .chars()
        .rev()
        .take(max_chars)
        .collect::<String>()
        .chars()
        .rev()
        .collect()
}

fn fetch_local_backend_version() -> Result<String, String> {
    let mut stream = TcpStream::connect("127.0.0.1:8765")
        .map_err(|err| format!("connect backend version failed: {}", err))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|err| format!("set backend read timeout failed: {}", err))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|err| format!("set backend write timeout failed: {}", err))?;
    stream
        .write_all(
            b"GET /api/v1/version HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nConnection: close\r\n\r\n",
        )
        .map_err(|err| format!("write backend version request failed: {}", err))?;
    let mut raw = String::new();
    stream
        .read_to_string(&mut raw)
        .map_err(|err| format!("read backend version response failed: {}", err))?;
    let body = raw
        .split("\r\n\r\n")
        .nth(1)
        .ok_or_else(|| "backend version response missing body".to_string())?;
    Ok(body.to_string())
}

fn backend_version_payload_matches_expected_build(payload: &str) -> bool {
    payload.contains(&format!("\"build_id\":\"{}\"", TERMINAL_RUNTIME_BUILD_ID))
}

fn existing_backend_mismatch_message(payload: &str) -> String {
    format!(
        "backend on 127.0.0.1:8765 is not the expected repo build {}. Stop the stale backend before launching desktop dev. version_payload={}",
        TERMINAL_RUNTIME_BUILD_ID,
        payload
    )
}

fn backend_matches_expected_build() -> Result<bool, String> {
    let payload = fetch_local_backend_version()?;
    Ok(backend_version_payload_matches_expected_build(&payload))
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let trimmed = url.trim();
    if !(trimmed.starts_with("https://") || trimmed.starts_with("http://")) {
        return Err("only http and https URLs can be opened".to_string());
    }
    if trimmed.chars().any(|value| value.is_control()) {
        return Err("URL contains control characters".to_string());
    }

    let mut command = if cfg!(windows) {
        let mut command = Command::new("cmd.exe");
        command.args(["/C", "start", "", trimmed]);
        command
    } else if cfg!(target_os = "macos") {
        let mut command = Command::new("open");
        command.arg(trimmed);
        command
    } else {
        let mut command = Command::new("xdg-open");
        command.arg(trimmed);
        command
    };

    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|err| format!("open URL failed: {}", err))?;
    Ok(())
}

fn wait_backend_ready(child: &mut Child, log_path: &Path, timeout: Duration) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect("127.0.0.1:8765").is_ok() {
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            let tail = read_log_tail(log_path, 1800);
            return Err(format!(
                "backend exited early with status {}. log={} tail=\n{}",
                status,
                log_path.display(),
                tail
            ));
        }
        thread::sleep(Duration::from_millis(250));
    }
    let tail = read_log_tail(log_path, 1800);
    Err(format!(
        "backend health check timeout on 127.0.0.1:8765. log={} tail=\n{}",
        log_path.display(),
        tail
    ))
}

fn desktop_startup_error_message(error: impl std::fmt::Display) -> String {
    format!("[ERROR] Desktop startup failed: {}", error)
}

fn run_desktop() -> tauri::Result<()> {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![open_external_url])
        .setup(|app| {
            if TcpStream::connect("127.0.0.1:8765").is_ok() {
                if cfg!(debug_assertions) {
                    if backend_matches_expected_build().unwrap_or(false) {
                        return Ok(());
                    }
                    let payload = fetch_local_backend_version()
                        .unwrap_or_else(|err| format!("failed to read /api/v1/version: {}", err));
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::AlreadyExists,
                        existing_backend_mismatch_message(&payload),
                    )
                    .into());
                }
                return Err(std::io::Error::new(
                    std::io::ErrorKind::AddrInUse,
                    "packaged desktop will not reuse an existing backend on 127.0.0.1:8765; stop it before launch",
                )
                .into());
            }
            let state: tauri::State<BackendState> = app.state();
            let mut spawned =
                spawn_backend().map_err(|msg| std::io::Error::new(std::io::ErrorKind::Other, msg))?;
            if let Err(err) = wait_backend_ready(&mut spawned.child, &spawned.log_path, Duration::from_secs(20)) {
                terminate_backend_child(&mut spawned.child);
                return Err(std::io::Error::new(std::io::ErrorKind::TimedOut, err).into());
            }
            let mut guard = state
                .0
                .lock()
                .map_err(|_| std::io::Error::new(std::io::ErrorKind::Other, "backend lock poisoned"))?;
            *guard = Some(spawned.child);
            Ok(())
        })
        .build(tauri::generate_context!())?;
    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            let state: tauri::State<BackendState> = app_handle.state();
            let lock_result = state.0.lock();
            if let Ok(mut guard) = lock_result {
                if let Some(mut child) = guard.take() {
                    terminate_backend_child(&mut child);
                }
            }
        }
    });
    Ok(())
}

fn main() {
    if let Err(err) = run_desktop() {
        eprintln!("{}", desktop_startup_error_message(err));
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_version_payload_matches_expected_build_id() {
        let payload = r#"{"item":{"build_id":"terminal-websocket-v1","backend_source":"repo"}}"#;

        assert!(backend_version_payload_matches_expected_build(payload));
    }

    #[test]
    fn backend_version_mismatch_message_includes_payload() {
        let payload = r#"{"item":{"build_id":"old-build","backend_source":"run.bat:web"}}"#;
        let message = existing_backend_mismatch_message(payload);

        assert!(message.contains("terminal-websocket-v1"));
        assert!(message.contains("old-build"));
        assert!(message.contains("run.bat:web"));
    }

    #[test]
    fn desktop_startup_error_message_includes_error() {
        let message = desktop_startup_error_message("backend refused startup");

        assert!(message.contains("Desktop startup failed"));
        assert!(message.contains("backend refused startup"));
    }
}
