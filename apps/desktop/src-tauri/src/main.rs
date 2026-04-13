#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use std::{env, net::TcpStream, thread};
use tauri::Manager;

struct BackendState(Mutex<Option<Child>>);

struct PythonCommand {
    program: String,
    args: Vec<String>,
}

struct BackendCommand {
    program: String,
    args: Vec<String>,
    workdir: Option<PathBuf>,
}

struct SpawnedBackend {
    child: Child,
    log_path: PathBuf,
}

fn candidate_python_commands() -> Vec<PythonCommand> {
    if let Ok(explicit) = std::env::var("H2OMETA_PYTHON") {
        if !explicit.trim().is_empty() {
            return vec![PythonCommand {
                program: explicit,
                args: vec![],
            }];
        }
    }
    if cfg!(windows) {
        let conda_env = std::env::var("H2OMETA_CONDA_ENV")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| "bio_ui".to_string());
        let mut commands = Vec::new();

        if let Ok(explicit_conda) = std::env::var("H2OMETA_CONDA_EXE") {
            if !explicit_conda.trim().is_empty() {
                commands.push(PythonCommand {
                    program: explicit_conda,
                    args: vec![
                        "run".to_string(),
                        "-n".to_string(),
                        conda_env.clone(),
                        "python".to_string(),
                    ],
                });
            }
        }

        commands.push(PythonCommand {
            program: "C:\\Users\\Administrator\\miniconda3\\Scripts\\conda.exe".to_string(),
            args: vec![
                "run".to_string(),
                "-n".to_string(),
                conda_env,
                "python".to_string(),
            ],
        });

        commands.extend(vec![
            PythonCommand {
                program: "py".to_string(),
                args: vec!["-3".to_string()],
            },
            PythonCommand {
                program: "python".to_string(),
                args: vec![],
            },
            PythonCommand {
                program: "python3".to_string(),
                args: vec![],
            },
        ]);
        return commands;
    }
    vec![
        PythonCommand {
            program: "python3".to_string(),
            args: vec![],
        },
        PythonCommand {
            program: "python".to_string(),
            args: vec![],
        },
    ]
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
    }))
}

fn sibling_sidecar_command() -> Result<Option<BackendCommand>, String> {
    let exe_path = env::current_exe().map_err(|err| format!("resolve current exe failed: {}", err))?;
    let exe_dir = exe_path
        .parent()
        .ok_or_else(|| format!("cannot resolve parent dir for {}", exe_path.display()))?;
    let binary_name = if cfg!(windows) { "h2ometa-api.exe" } else { "h2ometa-api" };
    let candidate = exe_dir.join(binary_name);
    if !candidate.exists() {
        return Ok(None);
    }
    Ok(Some(BackendCommand {
        program: candidate.display().to_string(),
        args: vec![],
        workdir: candidate.parent().map(|path| path.to_path_buf()),
    }))
}

fn dev_repo_backend_command() -> Result<Option<BackendCommand>, String> {
    let allow_repo_backend = env::var("H2OMETA_ALLOW_REPO_BACKEND")
        .ok()
        .map(|value| value == "1")
        .unwrap_or(false);
    if !allow_repo_backend {
        return Ok(None);
    }
    let workdir = repo_backend_workdir()?;
    Ok(Some(BackendCommand {
        program: String::new(),
        args: vec![],
        workdir: Some(workdir),
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
        cmd.args(cmd_spec.args.iter())
            .arg("-m")
            .arg("apps.api.run")
            .current_dir(&workdir)
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
        "no desktop backend launch target configured; set H2OMETA_BACKEND_EXE, bundle a sibling h2ometa-api sidecar, or opt into dev fallback with H2OMETA_ALLOW_REPO_BACKEND=1".to_string(),
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

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            if TcpStream::connect("127.0.0.1:8765").is_ok() {
                return Ok(());
            }
            let state: tauri::State<BackendState> = app.state();
            let mut spawned =
                spawn_backend().map_err(|msg| std::io::Error::new(std::io::ErrorKind::Other, msg))?;
            if let Err(err) = wait_backend_ready(&mut spawned.child, &spawned.log_path, Duration::from_secs(20)) {
                let _ = spawned.child.kill();
                return Err(std::io::Error::new(std::io::ErrorKind::TimedOut, err).into());
            }
            let mut guard = state
                .0
                .lock()
                .map_err(|_| std::io::Error::new(std::io::ErrorKind::Other, "backend lock poisoned"))?;
            *guard = Some(spawned.child);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state: tauri::State<BackendState> = app_handle.state();
                let lock_result = state.0.lock();
                if let Ok(mut guard) = lock_result {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
