#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use std::{net::TcpStream, thread};
use tauri::Manager;

struct BackendState(Mutex<Option<Child>>);

struct PythonCommand {
    program: String,
    args: Vec<String>,
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
        return vec![
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
        ];
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

fn has_backend_entry(path: &std::path::Path) -> bool {
    path.join("apps").join("api").join("run.py").exists()
}

fn locate_repo_root_from(start: &std::path::Path) -> Option<PathBuf> {
    let mut cursor = Some(start);
    while let Some(path) = cursor {
        if has_backend_entry(path) {
            return Some(path.to_path_buf());
        }
        cursor = path.parent();
    }
    None
}

fn backend_workdir() -> Result<PathBuf, String> {
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

fn spawn_backend() -> Result<SpawnedBackend, String> {
    let workdir = backend_workdir()?;
    let log_path = workdir.join("logs").join("desktop_backend_boot.log");
    let mut last_error = String::from("no python command available");
    let _ = std::fs::create_dir_all(workdir.join("logs"));

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

fn read_log_tail(log_path: &std::path::Path, max_chars: usize) -> String {
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

fn wait_backend_ready(child: &mut Child, log_path: &std::path::Path, timeout: Duration) -> Result<(), String> {
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
