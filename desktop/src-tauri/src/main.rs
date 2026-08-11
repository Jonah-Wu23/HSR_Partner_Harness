#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};
use tauri::{Emitter, Manager, State};

type PendingMap = Arc<Mutex<HashMap<String, Sender<Value>>>>;

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
    let candidate = resource_root
        .join("sidecar")
        .join("pair-harness-sidecar")
        .join("pair-harness-sidecar.exe");
    candidate.is_file().then_some(candidate)
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<BackendState, String> {
    let packaged = packaged_sidecar(app);
    let root = std::env::var_os("PAIR_HARNESS_ROOT")
        .map(PathBuf::from)
        .or_else(|| packaged.as_ref().and_then(|path| path.parent().map(PathBuf::from)))
        .unwrap_or_else(repository_root);
    let program = packaged.clone().unwrap_or_else(|| python_command(&root));
    let mut command = Command::new(program);
    command.current_dir(&root);
    if packaged.is_some() {
        command.args(["--demo", "--project"]);
    } else {
        command.args(["-m", "pair_harness.desktop_backend", "--demo", "--project"]);
    }
    command
        .arg(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

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
fn desktop_request(request: Value, state: State<'_, BackendState>) -> Result<Value, String> {
    let id = request
        .get("id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "桌面请求缺少 id".to_string())?
        .to_string();
    let line = encode_request_line(&request)?;
    let (sender, receiver): (Sender<Value>, Receiver<Value>) = mpsc::channel();
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
        .recv_timeout(Duration::from_secs(60))
        .map_err(|error| format!("等待 Sidecar 响应失败：{error}"))
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
    tauri::Builder::default()
        .setup(|app| {
            let state = spawn_backend(app.handle())?;
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
    use super::{encode_request_line, fail_pending, PendingMap};
    use serde_json::json;
    use std::collections::HashMap;
    use std::sync::{mpsc, Arc, Mutex};

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
    fn disconnected_sidecar_releases_pending_request() {
        let (sender, receiver) = mpsc::channel();
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::from([("r1".to_string(), sender)])));
        fail_pending(&pending, "断开");
        let value = receiver.recv().unwrap();
        assert_eq!(value["ok"], false);
        assert_eq!(value["error"]["code"], "backend_disconnected");
    }
}
