#![cfg_attr(windows, windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde_json::{json, Value};
use tauri::{Emitter, Manager, State};

type PendingMap = Arc<Mutex<HashMap<String, tokio::sync::oneshot::Sender<Value>>>>;

/// 自动重连退避起点（秒）：首次立即重试，失败后按 1s → 2s → 4s → 8s → 15s 递增。
const BACKOFF_START_SECS: u64 = 1;
/// 退避上限（秒）。
const BACKOFF_MAX_SECS: u64 = 15;

/// 第 attempt 次重试前的等待时长；第 0 次立即重试，此后 1s/2s/4s…，上限 15s。
fn backoff_delay(attempt: u32) -> Duration {
    if attempt == 0 {
        return Duration::ZERO;
    }
    let shift = u32::min(attempt - 1, 8); // 1 << 8 = 256s，最终由上限截断
    let seconds = BACKOFF_START_SECS << shift;
    Duration::from_secs(u64::min(seconds, BACKOFF_MAX_SECS))
}

/// 读取线程 EOF 时对退出原因的归类，决定是否自动重连。
#[derive(Debug, PartialEq, Eq)]
enum ExitClass {
    /// app.shutdown 主动关闭：不重连，也不向前端发断开事件。
    Shutdown,
    /// 进程自行正常退出（exit 0）：通知前端断开，但不自动重连，等用户手动重连。
    CleanExit,
    /// 异常退出（非零退出码，或子进程被外力取走）：通知前端并自动重连。
    Crash(Option<i32>),
}

fn classify_exit(shutdown: bool, status: Option<ExitStatus>) -> ExitClass {
    if shutdown {
        return ExitClass::Shutdown;
    }
    match status {
        Some(status) if status.success() => ExitClass::CleanExit,
        _ => ExitClass::Crash(status.and_then(|status| status.code())),
    }
}

struct BackendState {
    /// 用于发事件与重新 spawn（退避循环在后台线程运行）。
    app: tauri::AppHandle,
    debug_console: bool,
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    pending: PendingMap,
    /// stop_backend 置位后不再自动重连。
    shutdown: AtomicBool,
    /// 是否有恢复循环正在运行（EOF 触发与手动重连互斥，避免重复 spawn）。
    reconnecting: AtomicBool,
    /// 连接状态观察通道：false=断开，true=恢复；sidecar_reconnect 等待恢复用。
    connection: tokio::sync::watch::Sender<bool>,
    /// 最近一次 spawn 失败原因，供排查。
    last_error: Mutex<Option<String>>,
    /// 连续异常退出计数：退避跨 EOF 周期延续，避免「启动即崩」的忙循环；
    /// 新进程吐出首条合法输出时清零，手动重连时也清零（重置退避）。
    crash_streak: Mutex<u32>,
    /// 本进程侧的单调事件序号：跟踪 Sidecar 事件的最大序号，合成事件取其后续，
    /// 保证前端序列号校验在断线-重连之间不断层。
    last_sequence: AtomicU64,
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

fn packaged_reasonix(app: &tauri::AppHandle) -> Option<PathBuf> {
    let resource_root = app.path().resource_dir().ok()?;
    for root in [resource_root.clone(), resource_root.join("resources")] {
        let candidate = root.join("reasonix").join("bin").join("reasonix.exe");
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

/// 拉起一个 Sidecar 进程并取回它的 stdin/stdout 句柄（不启动读取线程）。
fn launch_sidecar(
    app: &tauri::AppHandle,
    debug_console: bool,
) -> Result<(Child, ChildStdin, ChildStdout), String> {
    let packaged = packaged_sidecar(app);
    let bundled_codex = packaged_codex(app);
    let bundled_reasonix = packaged_reasonix(app);
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
    if let Some(reasonix) = bundled_reasonix {
        command.env("PAIR_HARNESS_BUNDLED_REASONIX_BIN", reasonix);
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
    Ok((child, stdin, stdout))
}

impl BackendState {
    /// 合成事件序号：取 Sidecar 已见最大序号的下一个，保证前端单调校验不断层。
    fn next_event_sequence(&self) -> u64 {
        self.last_sequence.fetch_add(1, Ordering::SeqCst) + 1
    }

    /// 断开广播：connection.status disconnected + error.reported（recoverable）。
    fn publish_disconnected(&self, message: &str) {
        let _ = self.connection.send(false);
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "connection.status",
                "sequence": self.next_event_sequence(),
                "payload": {"status": "disconnected"}
            }),
        );
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "error.reported",
                "sequence": self.next_event_sequence(),
                "payload": {
                    "code": "backend_disconnected",
                    "message": message,
                    "severity": "recoverable",
                    "source": "sidecar"
                }
            }),
        );
    }

    /// 恢复广播：connection.status connected，前端随后重新 bootstrap。
    fn publish_connected(&self) {
        let _ = self.connection.send(true);
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "connection.status",
                "sequence": self.next_event_sequence(),
                "payload": {"status": "connected"}
            }),
        );
    }

    /// 重新拉起 Sidecar：成功后新旧 stdin/child 已交换，失败返回原因。
    fn respawn(&self) -> Result<ChildStdout, String> {
        let (child, stdin, stdout) = launch_sidecar(&self.app, self.debug_console)?;
        *self.stdin.lock().unwrap() = Some(stdin);
        *self.child.lock().unwrap() = Some(child);
        Ok(stdout)
    }

    /// 带退避的自动重连循环；成功后发 connected 并启动新读取线程。
    /// 退避从持久化的崩溃计数起步：单次崩溃立即重试，连续崩溃（启动即崩）
    /// 时按 1s/2s/4s…15s 跨 EOF 周期递增，避免忙循环。
    fn reconnect_loop(self: &Arc<Self>) {
        let mut attempt = self.crash_streak.lock().unwrap().saturating_sub(1);
        loop {
            if self.shutdown.load(Ordering::SeqCst) {
                break;
            }
            if attempt > 0 {
                std::thread::sleep(backoff_delay(attempt));
                if self.shutdown.load(Ordering::SeqCst) {
                    break;
                }
            }
            match self.respawn() {
                Ok(stdout) => {
                    self.publish_connected();
                    start_reader(self, stdout);
                    break;
                }
                Err(error) => {
                    *self.last_error.lock().unwrap() = Some(error.clone());
                    eprintln!("[sidecar] 重启失败（第 {attempt} 次）：{error}");
                    attempt += 1;
                    *self.crash_streak.lock().unwrap() = attempt.saturating_add(1);
                }
            }
        }
        self.reconnecting.store(false, Ordering::SeqCst);
    }

    /// 启动恢复循环；已有进程存活或已有循环在跑时跳过。
    fn ensure_reconnect_loop(self: &Arc<Self>) {
        if self.child.lock().unwrap().is_some() {
            return; // 已有进程存活，无需重连
        }
        if self.reconnecting.swap(true, Ordering::SeqCst) {
            return; // 恢复循环已在运行
        }
        let state = Arc::clone(self);
        std::thread::spawn(move || state.reconnect_loop());
    }
}

fn spawn_backend(app: &tauri::AppHandle, debug_console: bool) -> Result<Arc<BackendState>, String> {
    let (child, stdin, stdout) = launch_sidecar(app, debug_console)?;
    let (connection, _) = tokio::sync::watch::channel(true);
    let state = Arc::new(BackendState {
        app: app.clone(),
        debug_console,
        child: Mutex::new(Some(child)),
        stdin: Mutex::new(Some(stdin)),
        pending: Arc::new(Mutex::new(HashMap::new())),
        shutdown: AtomicBool::new(false),
        reconnecting: AtomicBool::new(false),
        connection,
        last_error: Mutex::new(None),
        crash_streak: Mutex::new(0),
        last_sequence: AtomicU64::new(0),
    });
    start_reader(&state, stdout);
    Ok(state)
}

/// 读取线程：把 Sidecar 的 stdout JSONL 转发为 sidecar://event，EOF 时按退出原因处理。
fn start_reader(state: &Arc<BackendState>, stdout: ChildStdout) {
    let state = Arc::clone(state);
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            // 进程吐出合法输出说明已稳定存活，清零连续崩溃计数
            *state.crash_streak.lock().unwrap() = 0;
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                let _ = state.app.emit(
                    "sidecar://event",
                    json!({
                        "kind": "event",
                        "event": "error.reported",
                        "sequence": state.next_event_sequence(),
                        "payload": {"code": "invalid_sidecar_json", "message": "Sidecar 输出不是合法 JSON"}
                    }),
                );
                continue;
            };
            if let Some(sequence) = value.get("sequence").and_then(Value::as_u64) {
                let _ = state.last_sequence.fetch_max(sequence, Ordering::SeqCst);
            }
            let routed_to_pending = matches!(
                value.get("kind").and_then(Value::as_str),
                Some("response") | Some("error")
            );
            if routed_to_pending {
                if let Some(id) = value.get("id").and_then(Value::as_str) {
                    if let Some(sender) = state.pending.lock().unwrap().remove(id) {
                        let routed = if value.get("kind")
                            == Some(&Value::String("error".to_string()))
                        {
                            json!({
                                "kind": "response",
                                "id": id,
                                "ok": false,
                                "error": value.get("error").cloned().unwrap_or_else(|| json!({"code": "protocol_error", "message": "Sidecar 协议错误"}))
                            })
                        } else {
                            value
                        };
                        let _ = sender.send(routed);
                    }
                }
            } else {
                let _ = state.app.emit("sidecar://event", value);
            }
        }
        // ---- EOF：先清掉所有在途请求，再按退出原因分类处理 ----
        fail_pending(&state.pending, "Python Sidecar 已断开");
        let exit_status = state
            .child
            .lock()
            .unwrap()
            .take()
            .and_then(|mut child| child.wait().ok());
        match classify_exit(state.shutdown.load(Ordering::SeqCst), exit_status) {
            ExitClass::Shutdown => {} // 主动关闭：不发事件也不重连
            ExitClass::CleanExit => {
                state.publish_disconnected("Python Sidecar 已退出");
            }
            ExitClass::Crash(_) => {
                let mut streak = state.crash_streak.lock().unwrap();
                *streak = streak.saturating_add(1);
                drop(streak);
                state.publish_disconnected("Python Sidecar 已断开，正在重连…");
                state.ensure_reconnect_loop();
            }
        }
    });
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
async fn desktop_request(
    request: Value,
    state: State<'_, Arc<BackendState>>,
) -> Result<Value, String> {
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
            None => Err("Sidecar 已断开：等待自动重连或点击立即重连".to_string()),
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

/// 前端「立即重连」：强制终止现有 Sidecar 并立即重启（重置退避），
/// 等待连接恢复后返回；超时或应用关闭时返回错误。
#[tauri::command]
async fn sidecar_reconnect(state: State<'_, Arc<BackendState>>) -> Result<Value, String> {
    if state.shutdown.load(Ordering::SeqCst) {
        return Err("应用正在退出，无法重连".to_string());
    }
    // 手动重连重置退避：即使此前连续崩溃，也立即尝试一次
    *state.crash_streak.lock().unwrap() = 0;
    // 强制终止现有进程（若有）；其 EOF 或恢复循环负责立即重启
    if let Some(mut child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let _ = state.stdin.lock().unwrap().take();
    state.ensure_reconnect_loop();

    // 等待恢复循环发出 connected；先消费当前值，避免错过已完成的恢复
    let mut receiver = state.connection.subscribe();
    if *receiver.borrow() {
        return Ok(json!({ "reconnected": true }));
    }
    tokio::time::timeout(Duration::from_secs(30), async move {
        loop {
            if receiver.changed().await.is_err() {
                return Err("连接状态通道已关闭".to_string());
            }
            if *receiver.borrow_and_update() {
                return Ok(());
            }
        }
    })
    .await
    .map_err(|_| "重连超时：本地服务未能恢复，请稍后再试".to_string())??;
    Ok(json!({ "reconnected": true }))
}

fn stop_backend(state: &BackendState) {
    state.shutdown.store(true, Ordering::SeqCst); // 主动关闭：禁止自动重连
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
        .invoke_handler(tauri::generate_handler![desktop_request, sidecar_reconnect])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<Arc<BackendState>>() {
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
    use super::{
        backoff_delay, classify_exit, debug_console_requested, encode_request_line, fail_pending,
        ExitClass, PendingMap,
    };
    use serde_json::json;
    use std::collections::HashMap;
    use std::process::ExitStatus;
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    #[cfg(unix)]
    use std::os::unix::process::ExitStatusExt;
    #[cfg(windows)]
    use std::os::windows::process::ExitStatusExt;

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

    // ------------------------------------------------------------------ M2-5 退出分类与退避

    #[test]
    fn normal_shutdown_never_reconnects() {
        // app.shutdown 流程：无论退出码如何都不重连
        assert_eq!(
            classify_exit(true, Some(ExitStatus::from_raw(0))),
            ExitClass::Shutdown
        );
        assert_eq!(
            classify_exit(true, Some(ExitStatus::from_raw(1))),
            ExitClass::Shutdown
        );
    }

    #[test]
    fn clean_exit_without_shutdown_does_not_reconnect() {
        // exit 0 且非主动关闭：通知断开，但不自动重连（留给手动重连）
        assert_eq!(
            classify_exit(false, Some(ExitStatus::from_raw(0))),
            ExitClass::CleanExit
        );
    }

    #[test]
    fn abnormal_exit_triggers_reconnect() {
        assert_eq!(
            classify_exit(false, Some(ExitStatus::from_raw(1))),
            ExitClass::Crash(Some(1))
        );
        assert_eq!(
            classify_exit(false, Some(ExitStatus::from_raw(2))),
            ExitClass::Crash(Some(2))
        );
        // 子进程被外力取走（无法取得退出码）也按异常处理
        assert_eq!(classify_exit(false, None), ExitClass::Crash(None));
    }

    #[test]
    fn backoff_starts_immediate_and_caps_at_max() {
        // 第 0 次立即重试
        assert_eq!(backoff_delay(0), Duration::ZERO);
        assert_eq!(backoff_delay(1), Duration::from_secs(1));
        assert_eq!(backoff_delay(2), Duration::from_secs(2));
        assert_eq!(backoff_delay(3), Duration::from_secs(4));
        assert_eq!(backoff_delay(4), Duration::from_secs(8));
        // 第 5 次起 16s 被截断为上限 15s，此后维持上限
        assert_eq!(backoff_delay(5), Duration::from_secs(15));
        assert_eq!(backoff_delay(100), Duration::from_secs(15));
    }
}
