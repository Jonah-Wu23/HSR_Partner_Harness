#![cfg_attr(windows, windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde_json::{json, Value};
use tauri::{Emitter, Manager, State};

type PendingMap = Arc<Mutex<HashMap<String, tokio::sync::oneshot::Sender<Value>>>>;

struct BackendState {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: PendingMap,
}
fn repository_root() -> PathBuf {
    std::env::var_os("PAIR_HARNESS_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
        })
}

fn python_command(root: &PathBuf) -> PathBuf {
    if let Some(value) = std::env::var_os("PAIR_HARNESS_PYTHON") {
        return PathBuf::from(value);
    }
    let venv_python = root.join(".venv").join("Scripts").join("python.exe");
    if venv_python.is_file() {
        return venv_python;
    }
    PathBuf::from("python")
}

fn packaged_sidecar(app: &tauri::AppHandle) -> Option<PathBuf> {
    let resource_root = app.path().resource_dir().ok()?;
    for root in [resource_root.clone(), resource_root.join("resources")] {
        let candidate = root
            .join("sidecar")
            .join("pair-harness-sidecar")
            .join("pair-harness-sidecar.exe");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn packaged_codex(app: &tauri::AppHandle) -> Option<PathBuf> {
    let resource_root = app.path().resource_dir().ok()?;
    for root in [resource_root.clone(), resource_root.join("resources")] {
        let candidate = root.join("codex").join("bin").join("codex.exe");
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn debug_console_requested<I>(args: I) -> bool
where
    I: IntoIterator<Item = String>,
{
    args.into_iter()
        .any(|arg| matches!(arg.as_str(), "--debug-console" | "--console"))
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn AllocConsole() -> i32;
    fn FreeConsole() -> i32;
}

#[cfg(windows)]
fn configure_console(debug_console: bool) {
    unsafe {
        if debug_console {
            let _ = AllocConsole();
        } else {
            let _ = FreeConsole();
        }
    }
}

#[cfg(not(windows))]
fn configure_console(_debug_console: bool) {}

fn env_flag(name: &str) -> Option<bool> {
    match std::env::var(name).ok()?.to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Some(true),
        "0" | "false" | "no" | "off" => Some(false),
        _ => None,
    }
}

fn configured_env_file(app: &tauri::AppHandle, root: &Path) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(value) = std::env::var_os("PAIR_HARNESS_ENV_FILE") {
        candidates.push(PathBuf::from(value));
    }
    candidates.push(root.join(".env"));
    if let Ok(current_dir) = std::env::current_dir() {
        candidates.push(current_dir.join(".env"));
    }
    if let Ok(executable) = std::env::current_exe() {
        if let Some(parent) = executable.parent() {
            candidates.push(parent.join(".env"));
        }
    }
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        candidates.push(
            PathBuf::from(local_app_data)
                .join("PairHarness")
                .join(".env"),
        );
    }
    if let Ok(config_dir) = app.path().app_config_dir() {
        candidates.push(config_dir.join(".env"));
    }
    if let Ok(data_dir) = app.path().app_data_dir() {
        candidates.push(data_dir.join(".env"));
    }
    candidates.into_iter().find(|path| path.is_file())
}

fn use_real_backend(env_file: Option<&Path>) -> bool {
    if let Some(value) = env_flag("PAIR_HARNESS_REAL") {
        return value;
    }
    if env_flag("PAIR_HARNESS_DEMO") == Some(true) {
        return false;
    }
    env_file.is_some()
}

fn spawn_backend(app: &tauri::AppHandle, debug_console: bool) -> Result<BackendState, String> {
    let packaged = packaged_sidecar(app);
    let bundled_codex = packaged_codex(app);
    let root = std::env::var_os("PAIR_HARNESS_ROOT")
        .map(PathBuf::from)
        .or_else(|| {
            packaged
                .as_ref()
                .and_then(|path| path.parent().map(PathBuf::from))
        })
        .unwrap_or_else(repository_root);
    let program = packaged.clone().unwrap_or_else(|| python_command(&root));
    let env_file = configured_env_file(app, &root);
    let real = use_real_backend(env_file.as_deref());
    let mut command = Command::new(program);
    command.current_dir(&root);
    let mode = if real { "--real" } else { "--demo" };
    if packaged.is_some() {
        command.args([mode, "--project"]);
    } else {
        command.args(["-m", "pair_harness.desktop_backend", mode, "--project"]);
    }
    if let Some(env_file) = env_file {
        command.env("PAIR_HARNESS_ENV_FILE", env_file);
    }
    if let Some(codex) = bundled_codex {
        command.env("PAIR_HARNESS_BUNDLED_CODEX_BIN", codex);
    }
    command
        .arg(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    #[cfg(windows)]
    if !debug_console {
        command.creation_flags(0x08000000);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("启动 Python Sidecar 失败：{error}"))?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "Sidecar stdin 不可用".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Sidecar stdout 不可用".to_string())?;
    let pending: PendingMap = Arc::new(Mutex::new(HashMap::new()));
    let reader_pending = Arc::clone(&pending);
    let reader_app = app.clone();
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                let _ = reader_app.emit(
                    "sidecar://event",
                    json!({
                        "kind": "event",
                        "event": "error.reported",
                        "sequence": 0,
                        "payload": {"code": "invalid_sidecar_json", "message": "Sidecar 输出不是合法 JSON"}
                    }),
                );
                continue;
            };
            if value.get("kind") == Some(&Value::String("response".to_string())) {
                if let Some(id) = value.get("id").and_then(Value::as_str) {
                    if let Some(sender) = reader_pending.lock().unwrap().remove(id) {
                        let _ = sender.send(value);
                    }
                }
            } else {
                let _ = reader_app.emit("sidecar://event", value);
            }
        }
        fail_pending(&reader_pending, "Python Sidecar 已断开");
        let _ = reader_app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "error.reported",
                "sequence": 0,
                "payload": {"code": "backend_disconnected", "message": "Python Sidecar 已断开"}
            }),
        );
    });

    Ok(BackendState {
        child: Mutex::new(Some(child)),
        stdin: Mutex::new(Some(stdin)),
        pending,
    })
}

fn fail_pending(pending: &PendingMap, message: &str) {
    let mut pending = pending.lock().unwrap();
    for (_, sender) in pending.drain() {
        let _ = sender.send(json!({
            "kind": "response",
            "id": null,
            "ok": false,
            "error": {"code": "backend_disconnected", "message": message}
        }));
    }
}

fn encode_request_line(request: &Value) -> Result<Vec<u8>, String> {
    let mut line = serde_json::to_vec(request).map_err(|error| error.to_string())?;
    line.push(b'\n');
    Ok(line)
}

#[tauri::command]
async fn desktop_request(request: Value, state: State<'_, BackendState>) -> Result<Value, String> {
    let id = request
        .get("id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "桌面请求缺少 id".to_string())?
        .to_string();
    let line = encode_request_line(&request)?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    state.pending.lock().unwrap().insert(id.clone(), sender);

    let write_result = {
        let mut stdin = state.stdin.lock().unwrap();
        match stdin.as_mut() {
            Some(stream) => stream
                .write_all(&line)
                .and_then(|_| stream.flush())
                .map_err(|error| format!("写入 Sidecar stdin 失败：{error}")),
            None => Err("Sidecar stdin 已关闭".to_string()),
        }
    };
    if let Err(error) = write_result {
        state.pending.lock().unwrap().remove(&id);
        return Err(error);
    }

    receiver
        .await
        .map_err(|_| "等待 Sidecar 响应失败：响应通道已关闭".to_string())
}

fn stop_backend(state: &BackendState) {
    if let Some(mut stdin) = state.stdin.lock().unwrap().take() {
        if let Ok(line) = encode_request_line(&json!({
            "kind": "request",
            "id": "app-shutdown",
            "method": "app.shutdown",
            "params": {}
        })) {
            let _ = stdin.write_all(&line);
            let _ = stdin.flush();
        }
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let debug_console = debug_console_requested(std::env::args());
    configure_console(debug_console);
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(move |app| {
            let state = spawn_backend(app.handle(), debug_console)?;
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![desktop_request])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendState>() {
                    stop_backend(&state);
                }
            }
        });
}

fn main() {
    run();
}

#[cfg(test)]
mod tests {
    use super::{debug_console_requested, encode_request_line, fail_pending, PendingMap};
    use serde_json::json;
    use std::collections::HashMap;
    use std::sync::{Arc, Mutex};

    #[test]
    fn request_line_is_single_json_line() {
        let line = encode_request_line(&json!({
            "kind": "request",
            "id": "r1",
            "method": "app.bootstrap",
            "params": {}
        }))
        .unwrap();
        assert_eq!(line.last(), Some(&b'\n'));
        assert_eq!(
            line[..line.len() - 1]
                .iter()
                .filter(|byte| **byte == b'\n')
                .count(),
            0
        );
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&line[..line.len() - 1]).unwrap()["id"],
            "r1"
        );
    }

    #[test]
    fn debug_console_requires_explicit_flag() {
        assert!(!debug_console_requested([
            "hsr-partner-harness.exe".to_string()
        ]));
        assert!(debug_console_requested([
            "hsr-partner-harness.exe".to_string(),
            "--debug-console".to_string(),
        ]));
        assert!(debug_console_requested([
            "hsr-partner-harness.exe".to_string(),
            "--console".to_string(),
        ]));
    }

    #[tokio::test]
    async fn disconnected_sidecar_releases_pending_request() {
        let (sender, receiver) = tokio::sync::oneshot::channel();
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::from([("r1".to_string(), sender)])));
        fail_pending(&pending, "断开");
        let value = receiver.await.unwrap();
        assert_eq!(value["ok"], false);
        assert_eq!(value["error"]["code"], "backend_disconnected");
    }
}
