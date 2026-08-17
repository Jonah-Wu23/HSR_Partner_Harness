#![cfg_attr(windows, windows_subsystem = "windows")]

use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use serde_json::{json, Value};
use tauri::{Emitter, Manager, State};

type PendingMap = Arc<Mutex<HashMap<String, tokio::sync::oneshot::Sender<Value>>>>;

/// V0.3.2 M5：独立聊天窗口的元数据（label → 归属会话），用于改名同步标题。
#[derive(Debug, Clone)]
struct ChatWindowMeta {
    conversation_id: String,
    #[allow(dead_code)]
    project_id: String,
}

/// 桌面请求等待 Sidecar 响应的默认上限。
const REQUEST_TIMEOUT_SECS: u64 = 30;

/// 音色生成会串行调用多个真实远程接口，不适用普通请求的
/// 30 秒上限。Sidecar 断开时 `fail_pending` 仍会立即释放等待方。
fn request_timeout_secs(request: &Value) -> Option<u64> {
    match request.get("method").and_then(Value::as_str) {
        Some("voice.provision") => None,
        _ => Some(REQUEST_TIMEOUT_SECS),
    }
}

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
    /// 致命启动配置错误（Python 退出码 2）：停止自动重连，由启动失败页接管。
    Fatal(i32),
}

fn classify_exit(shutdown: bool, status: Option<ExitStatus>) -> ExitClass {
    if shutdown {
        return ExitClass::Shutdown;
    }
    match status {
        Some(status) if status.success() => ExitClass::CleanExit,
        Some(status) if status.code() == Some(2) => ExitClass::Fatal(2),
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
    /// 当前连接代次；每次拉起 Sidecar 都会换成新的 stream_id。
    current_stream_id: Mutex<u64>,
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
    /// V0.3.2 M5：独立聊天窗口登记表（窗口 label → 会话元数据）。
    chat_windows: Mutex<HashMap<String, ChatWindowMeta>>,
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

fn next_stream_id() -> u64 {
    static NEXT_STREAM_ID: AtomicU64 = AtomicU64::new(0);
    NEXT_STREAM_ID.fetch_add(1, Ordering::SeqCst) + 1
}

/// V0.3.2 M5：进程内唯一的 v4 形态 UUID（窗口 label / view_id 用）。
/// 窗口 label 只需在本进程生命周期内唯一；为避免引入新依赖，用时间戳 + 计数器
/// 经 xorshift 混合生成，并按 RFC 4122 置版本与变体位。
fn random_uuid_v4() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or(0);
    let count = COUNTER.fetch_add(1, Ordering::SeqCst);
    let mut state = nanos ^ count.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    let mut next_u64 = move || {
        state ^= state >> 12;
        state ^= state << 25;
        state ^= state >> 27;
        state.wrapping_mul(0x2545_F491_4F6C_DD1D)
    };
    let a = next_u64();
    let b = next_u64();
    let c = next_u64();
    let d = next_u64();
    format!(
        "{:08x}-{:04x}-4{:03x}-{:04x}-{:012x}",
        a as u32,
        (b >> 48) as u16,
        (b >> 32) & 0x0FFF,
        (((c >> 48) as u16) & 0x3FFF) | 0x8000,
        ((c & 0x0000_FFFF) << 32) | (d & 0xFFFF_FFFF),
    )
}

/// V0.3.2 M5：URL query 组件百分号编码（保留非保留字符 A-Za-z0-9-_.~）。
fn encode_query_component(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                encoded.push(byte as char)
            }
            _ => encoded.push_str(&format!("%{byte:02X}")),
        }
    }
    encoded
}

/// V0.3.2 M5：聊天窗口标题（会话名 + 应用名）。
fn chat_window_title(title: &str) -> String {
    format!("{title} · HSR Partner Harness")
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

fn sidecar_stderr_log_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    let data_dir = app.path().app_data_dir().ok()?;
    std::fs::create_dir_all(&data_dir).ok()?;
    Some(data_dir.join("sidecar.stderr.log"))
}

fn drain_sidecar_stderr(stderr: ChildStderr, log_path: Option<PathBuf>) {
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        let mut log =
            log_path.and_then(|path| OpenOptions::new().create(true).append(true).open(path).ok());
        let mut line = Vec::new();
        loop {
            line.clear();
            match reader.read_until(b'\n', &mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if let Some(file) = log.as_mut() {
                        let _ = file.write_all(&line);
                        let _ = file.flush();
                    }
                }
            }
        }
    });
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
    // 开发机直接运行 target/release EXE 时，Sidecar 的 runtime_root 位于
    // resources 目录，不能再靠 current_dir 反推出仓库根目录。
    candidates.push(repository_root().join(".env"));
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

fn env_file_has_real_config(path: &Path) -> bool {
    std::fs::read_to_string(path)
        .map(|contents| env_content_has_real_config(&contents))
        .unwrap_or(false)
}

fn env_content_has_real_config(contents: &str) -> bool {
    let mut dialogue_base = false;
    let mut dialogue_key = false;
    let mut dialogue_model = false;
    for raw_line in contents.lines() {
        let line = raw_line.trim();
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((raw_key, raw_value)) = line.split_once('=') else {
            continue;
        };
        let key = raw_key.trim();
        let value = raw_value.trim().trim_matches(|ch| ch == '\'' || ch == '"');
        if value.is_empty() || value.starts_with("replace-with-") {
            continue;
        }
        match key {
            "PAIR_HARNESS_DIALOGUE_BASE_URL" => dialogue_base = true,
            "PAIR_HARNESS_DIALOGUE_API_KEY" => dialogue_key = true,
            "PAIR_HARNESS_DIALOGUE_MODEL" => dialogue_model = true,
            _ => {}
        }
    }
    if let Some(value) = env_content_flag(contents, "PAIR_HARNESS_REAL") {
        return value;
    }
    if env_content_flag(contents, "PAIR_HARNESS_DEMO") == Some(true) {
        return false;
    }
    dialogue_base && dialogue_key && dialogue_model
}

fn env_content_flag(contents: &str, wanted_key: &str) -> Option<bool> {
    for raw_line in contents.lines() {
        let line = raw_line.trim();
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((raw_key, raw_value)) = line.split_once('=') else {
            continue;
        };
        if raw_key.trim() != wanted_key {
            continue;
        }
        let value = raw_value
            .trim()
            .trim_matches(|ch| ch == '\'' || ch == '"')
            .to_ascii_lowercase();
        return match value.as_str() {
            "1" | "true" | "yes" | "on" => Some(true),
            "0" | "false" | "no" | "off" => Some(false),
            _ => None,
        };
    }
    None
}

fn use_real_backend(env_file: Option<&Path>) -> bool {
    if let Some(value) = env_flag("PAIR_HARNESS_REAL") {
        return value;
    }
    if env_flag("PAIR_HARNESS_DEMO") == Some(true) {
        return false;
    }
    env_file.is_some_and(env_file_has_real_config)
}

fn stream_id_value(stream_id: u64) -> String {
    stream_id.to_string()
}

/// 拉起一个 Sidecar 进程并取回它的 stdin/stdout 句柄（不启动读取线程）。
///
/// M2.1：每次启动都生成新的 `stream_id` 并通过环境变量传给 Python，事件按代次隔离。
/// M2.5：`runtime_root`（进程工作目录/可执行文件位置）与 `initial_project_root`
/// （首次启动默认项目根，必须位于可写的 app_data_dir）分开，不再复用同一个 root。
fn launch_sidecar(
    app: &tauri::AppHandle,
    debug_console: bool,
    stream_id: u64,
) -> Result<(Child, ChildStdin, ChildStdout), String> {
    let packaged = packaged_sidecar(app);
    let bundled_codex = packaged_codex(app);
    let bundled_reasonix = packaged_reasonix(app);
    let runtime_root = std::env::var_os("PAIR_HARNESS_ROOT")
        .map(PathBuf::from)
        .or_else(|| {
            packaged
                .as_ref()
                .and_then(|path| path.parent().map(PathBuf::from))
        })
        .unwrap_or_else(repository_root);
    let initial_project_root = app
        .path()
        .app_data_dir()
        .map(|data_dir| data_dir.join("projects").join("initial-project"))
        .map_err(|error| format!("读取应用数据目录失败：{error}"))?;
    std::fs::create_dir_all(&initial_project_root)
        .map_err(|error| format!("创建初始项目根失败：{error}"))?;
    let program = packaged
        .clone()
        .unwrap_or_else(|| python_command(&runtime_root));
    let env_file = configured_env_file(app, &runtime_root);
    let real = use_real_backend(env_file.as_deref());
    let stderr_log = sidecar_stderr_log_path(app);
    let mut command = Command::new(program);
    command.current_dir(&runtime_root);
    let mode = if real { "--real" } else { "--demo" };
    if packaged.is_some() {
        command
            .arg(mode)
            .arg("--project")
            .arg(&initial_project_root);
    } else {
        command
            .args(["-m", "pair_harness.desktop_backend", mode, "--project"])
            .arg(&initial_project_root);
    }
    command.env("PAIR_HARNESS_STREAM_ID", stream_id.to_string());
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
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    if !debug_console {
        command.creation_flags(0x08000000);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("启动 Python Sidecar 失败：{error}"))?;
    if let Some(stderr) = child.stderr.take() {
        drain_sidecar_stderr(stderr, stderr_log);
    }
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
        let stream_id = *self.current_stream_id.lock().unwrap();
        let _ = self.connection.send(false);
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "connection.status",
                "sequence": self.next_event_sequence(),
                "stream_id": stream_id_value(stream_id),
                "payload": {"status": "disconnected", "stream_id": stream_id_value(stream_id)}
            }),
        );
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "error.reported",
                "sequence": self.next_event_sequence(),
                "stream_id": stream_id_value(stream_id),
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
        let stream_id = *self.current_stream_id.lock().unwrap();
        let _ = self.connection.send(true);
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "connection.status",
                "sequence": self.next_event_sequence(),
                "stream_id": stream_id_value(stream_id),
                "payload": {"status": "connected", "stream_id": stream_id_value(stream_id)}
            }),
        );
    }

    /// 重新拉起 Sidecar：成功后新旧 stdin/child 已交换，失败返回原因。
    fn respawn(&self) -> Result<ChildStdout, String> {
        let stream_id = next_stream_id();
        let (child, stdin, stdout) = launch_sidecar(&self.app, self.debug_console, stream_id)?;
        *self.current_stream_id.lock().unwrap() = stream_id;
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
                    let stream_id = *self.current_stream_id.lock().unwrap();
                    self.publish_connected();
                    start_reader(self, stdout, stream_id);
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
    let stream_id = next_stream_id();
    let (child, stdin, stdout) = launch_sidecar(app, debug_console, stream_id)?;
    let (connection, _) = tokio::sync::watch::channel(true);
    let state = Arc::new(BackendState {
        app: app.clone(),
        debug_console,
        child: Mutex::new(Some(child)),
        stdin: Mutex::new(Some(stdin)),
        pending: Arc::new(Mutex::new(HashMap::new())),
        current_stream_id: Mutex::new(stream_id),
        shutdown: AtomicBool::new(false),
        reconnecting: AtomicBool::new(false),
        connection,
        last_error: Mutex::new(None),
        crash_streak: Mutex::new(0),
        last_sequence: AtomicU64::new(0),
        chat_windows: Mutex::new(HashMap::new()),
    });
    start_reader(&state, stdout, stream_id);
    Ok(state)
}

/// 读取线程：把 Sidecar 的 stdout JSONL 转发为 sidecar://event，EOF 时按退出原因处理。
///
/// M2.1：每个读取线程绑定自己的 `stream_id`；一旦当前代次已经换成新进程，
/// 旧 reader 必须立即退出，不能转发迟到事件或把新连接标成 disconnected。
fn start_reader(state: &Arc<BackendState>, stdout: ChildStdout, stream_id: u64) {
    let state = Arc::clone(state);
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if *state.current_stream_id.lock().unwrap() != stream_id {
                break; // 旧代次 reader 不得再处理本进程任何输出
            }
            let Ok(line) = line else { break };
            // 进程吐出合法输出说明已稳定存活，清零连续崩溃计数
            *state.crash_streak.lock().unwrap() = 0;
            let Ok(value) = serde_json::from_str::<Value>(&line) else {
                if *state.current_stream_id.lock().unwrap() != stream_id {
                    break;
                }
                let _ = state.app.emit(
                    "sidecar://event",
                    json!({
                        "kind": "event",
                        "event": "error.reported",
                        "sequence": state.next_event_sequence(),
                        "stream_id": stream_id_value(stream_id),
                        "payload": {"code": "invalid_sidecar_json", "message": "Sidecar 输出不是合法 JSON"}
                    }),
                );
                continue;
            };
            if *state.current_stream_id.lock().unwrap() != stream_id {
                break;
            }
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
                // V0.3.2 M5：会话改名时同步所有打开该会话的聊天窗口标题。
                sync_chat_window_titles(&state, &value);
                let _ = state.app.emit("sidecar://event", value);
            }
        }
        // EOF：只有当前代次的 reader 才能清 pending、取退出状态和广播。
        if *state.current_stream_id.lock().unwrap() != stream_id {
            return;
        }
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
            ExitClass::Fatal(code) => {
                let message = format!("Sidecar 启动配置错误，已停止自动重连（退出码 {code}）");
                *state.last_error.lock().unwrap() = Some(message.clone());
                eprintln!("[sidecar] 致命启动失败：{message}");
                // Python 侧已发出带 fatal 的 error.reported；这里只把连接观察值
                // 置为断开，避免前端等待重连。自动重连不启动。
                let _ = state.connection.send(false);
            }
        }
    });
}

fn fail_pending(pending: &PendingMap, message: &str) {
    let mut pending = pending.lock().unwrap();
    for (id, sender) in pending.drain() {
        let _ = sender.send(json!({
            "kind": "response",
            "id": id,
            "ok": false,
            "error": {"code": "backend_disconnected", "message": message}
        }));
    }
}

/// V0.3.2 M5：conversation.changed 事件到达时，更新所有打开该会话的
/// 独立聊天窗口标题（标签栏标题由前端各自消费事件更新）。
fn sync_chat_window_titles(state: &Arc<BackendState>, value: &Value) {
    if value.get("event").and_then(Value::as_str) != Some("conversation.changed") {
        return;
    }
    let Some(conversation) = value.get("payload").and_then(|payload| payload.get("conversation"))
    else {
        return;
    };
    let Some(conversation_id) = conversation
        .get("conversation_id")
        .and_then(Value::as_str)
        .map(str::to_string)
    else {
        return;
    };
    let title = conversation
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let window_title = chat_window_title(title);
    let labels: Vec<String> = state
        .chat_windows
        .lock()
        .unwrap()
        .iter()
        .filter(|(_, meta)| meta.conversation_id == conversation_id)
        .map(|(label, _)| label.clone())
        .collect();
    for label in labels {
        if let Some(window) = state.app.get_webview_window(&label) {
            let _ = window.set_title(&window_title);
        }
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
    let timeout_secs = request_timeout_secs(&request);
    let line = encode_request_line(&request)?;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    state.pending.lock().unwrap().insert(id.clone(), sender);

    // M1.6：阻塞 stdin 写入移出 Tokio worker。写入任务在 blocking 线程池里
    // 持有 Mutex，避免事件循环被管道写入卡住。
    let write_state = Arc::clone(&state);
    let write_result = match tokio::task::spawn_blocking(move || {
        let mut stdin = write_state.stdin.lock().unwrap();
        match stdin.as_mut() {
            Some(stream) => stream
                .write_all(&line)
                .and_then(|_| stream.flush())
                .map_err(|error| format!("写入 Sidecar stdin 失败：{error}")),
            None => Err("Sidecar 已断开：等待自动重连或点击立即重连".to_string()),
        }
    })
    .await
    {
        Ok(result) => result,
        Err(error) => {
            state.pending.lock().unwrap().remove(&id);
            return Err(format!("Sidecar 写入任务失败：{error}"));
        }
    };

    if let Err(error) = write_result {
        state.pending.lock().unwrap().remove(&id);
        state.publish_disconnected(&error);
        return Err(error);
    }

    if let Some(seconds) = timeout_secs {
        match tokio::time::timeout(Duration::from_secs(seconds), receiver).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(_)) => {
                state.pending.lock().unwrap().remove(&id);
                Err("等待 Sidecar 响应失败：响应通道已关闭".to_string())
            }
            Err(_) => {
                state.pending.lock().unwrap().remove(&id);
                Err(format!(
                    "backend_timeout: 等待 Sidecar 响应超过 {seconds} 秒（id={id}）"
                ))
            }
        }
    } else {
        match receiver.await {
            Ok(value) => Ok(value),
            Err(_) => {
                state.pending.lock().unwrap().remove(&id);
                Err("等待 Sidecar 响应失败：响应通道已关闭".to_string())
            }
        }
    }
}

/// 前端「立即重连」：强制终止现有 Sidecar 并立即重启（重置退避），
/// 等待连接恢复后返回；超时或应用关闭时返回错误。
#[tauri::command]
async fn sidecar_reconnect(state: State<'_, Arc<BackendState>>) -> Result<Value, String> {
    if state.shutdown.load(Ordering::SeqCst) {
        return Err("应用正在退出，无法重连".to_string());
    }
    // M2.3：手动重连先把当前连接状态置为 false，再启动新代次。
    // 不能读取旧 watch 值提前返回成功。
    let _ = state.connection.send(false);
    // 让旧 reader 立刻失效，防止其迟到的 EOF 覆盖新连接状态。
    *state.current_stream_id.lock().unwrap() = u64::MAX;
    // 手动重连重置退避：即使此前连续崩溃，也立即尝试一次
    *state.crash_streak.lock().unwrap() = 0;
    // 强制终止现有进程（若有）；其 EOF 或恢复循环负责立即重启
    if let Some(mut child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let _ = state.stdin.lock().unwrap().take();
    state.ensure_reconnect_loop();

    // 订阅在发送 false 之后进行；此时若已经变为 true，只能是新代次发布
    // connected（旧 reader 已失效，不会反向写 false）。
    let mut receiver = state.connection.subscribe();
    if *receiver.borrow_and_update() {
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

/// V0.3.2 M5：打开独立聊天窗口。
///
/// - 每次调用创建独立 WebviewWindow；label 用 `chat-{uuid}`（同一聊天允许
///   开多个窗口，不能用 conversation_id 做 label）。
/// - 窗口 URL 携带编码后的 conversation_id 与新 view_id，React 启动后调用
///   conversation.open 装载该聊天。
/// - 新窗口与主窗口共享同一个 Rust BackendState、Python Sidecar 与事件广播。
#[tauri::command]
async fn open_chat_window(
    app: tauri::AppHandle,
    state: State<'_, Arc<BackendState>>,
    conversation_id: String,
    project_id: String,
    title: String,
) -> Result<String, String> {
    let window_id = random_uuid_v4();
    let view_id = random_uuid_v4();
    let label = format!("chat-{window_id}");
    let url_path = format!(
        "index.html?conversation_id={}&view_id={}",
        encode_query_component(&conversation_id),
        encode_query_component(&view_id),
    );
    let window = tauri::WebviewWindowBuilder::new(
        &app,
        &label,
        tauri::WebviewUrl::App(std::path::PathBuf::from(url_path)),
    )
    .title(chat_window_title(&title))
    .inner_size(980.0, 700.0)
    .min_inner_size(720.0, 520.0)
    .build()
    .map_err(|error| format!("创建聊天窗口失败：{error}"))?;
    let _ = window.show();
    state.chat_windows.lock().unwrap().insert(
        label.clone(),
        ChatWindowMeta {
            conversation_id,
            project_id,
        },
    );
    Ok(label)
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
    let deadline = Instant::now() + Duration::from_secs(5);
    if let Some(mut child) = state.child.lock().unwrap().take() {
        // M2.4：先给 Python 有限时间优雅退出，超时再强制结束。
        loop {
            if let Ok(Some(_status)) = child.try_wait() {
                break;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
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
        .on_window_event(|window, event| {
            // V0.3.2 M5：聊天窗口销毁时从登记表移除（不影响其他窗口与 Sidecar）。
            if matches!(event, tauri::WindowEvent::Destroyed) {
                if let Some(state) = window.app_handle().try_state::<Arc<BackendState>>() {
                    state.chat_windows.lock().unwrap().remove(window.label());
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            desktop_request,
            sidecar_reconnect,
            open_chat_window
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // V0.3.2 M5：关闭任意聊天窗口只是销毁该窗口，不触发退出流程；
            // 只有最后一个应用窗口退出（ExitRequested 且已无窗口）才进入退出，
            // 在 Exit 时停止 Sidecar。仍存在窗口时拒绝退出请求（防御）。
            if let tauri::RunEvent::ExitRequested { code: None, ref api, .. } = event {
                if !app_handle.webview_windows().is_empty() {
                    api.prevent_exit();
                    return;
                }
            }
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
        backoff_delay, classify_exit, debug_console_requested, encode_request_line,
        env_content_has_real_config, fail_pending, request_timeout_secs, stream_id_value,
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
    fn voice_provision_is_not_limited_by_the_default_request_timeout() {
        assert_eq!(
            request_timeout_secs(&json!({"method": "voice.provision"})),
            None
        );
        assert_eq!(
            request_timeout_secs(&json!({"method": "config.get"})),
            Some(30)
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
        assert_eq!(value["id"], "r1");
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
            classify_exit(false, Some(ExitStatus::from_raw(3))),
            ExitClass::Crash(Some(3))
        );
        // 子进程被外力取走（无法取得退出码）也按异常处理
        assert_eq!(classify_exit(false, None), ExitClass::Crash(None));
    }

    #[test]
    fn fatal_config_exit_code_stops_reconnect() {
        assert_eq!(
            classify_exit(false, Some(ExitStatus::from_raw(2))),
            ExitClass::Fatal(2)
        );
        // 主动关闭优先级最高，不因退出码 2 改变分类
        assert_eq!(
            classify_exit(true, Some(ExitStatus::from_raw(2))),
            ExitClass::Shutdown
        );
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

    #[test]
    fn stream_id_is_serialized_as_a_string() {
        assert_eq!(stream_id_value(42), "42");
    }

    // ------------------------------------------------- V0.3.2 M5 聊天窗口辅助

    #[test]
    fn query_component_encodes_reserved_characters() {
        use super::{chat_window_title, encode_query_component};
        assert_eq!(encode_query_component("conv-1"), "conv-1");
        assert_eq!(encode_query_component("a b&c=d"), "a%20b%26c%3Dd");
        assert_eq!(encode_query_component("中文"), "%E4%B8%AD%E6%96%87");
        assert_eq!(chat_window_title("奥赫玛"), "奥赫玛 · HSR Partner Harness");
    }

    #[test]
    fn window_uuid_is_unique_and_v4_shaped() {
        use super::random_uuid_v4;
        let first = random_uuid_v4();
        let second = random_uuid_v4();
        assert_ne!(first, second);
        // 8-4-4-4-12 十六进制段，版本 4、变体 8/9/a/b
        let segments: Vec<&str> = first.split('-').collect();
        assert_eq!(
            segments.iter().map(|segment| segment.len()).collect::<Vec<_>>(),
            vec![8, 4, 4, 4, 12]
        );
        assert!(segments[2].starts_with('4'));
        assert!(matches!(
            segments[3].chars().next(),
            Some('8') | Some('9') | Some('a') | Some('b')
        ));
        assert!(first.chars().all(|ch| ch.is_ascii_hexdigit() || ch == '-'));
    }

    #[test]
    fn env_file_requires_real_dialogue_configuration() {
        assert!(env_content_has_real_config(
            "PAIR_HARNESS_DIALOGUE_BASE_URL=https://example.test\nPAIR_HARNESS_DIALOGUE_API_KEY=secret\nPAIR_HARNESS_DIALOGUE_MODEL=model\n"
        ));
        assert!(env_content_has_real_config("PAIR_HARNESS_REAL=1\n"));
        assert!(!env_content_has_real_config(
            "PAIR_HARNESS_REAL=0\nPAIR_HARNESS_DIALOGUE_BASE_URL=https://example.test\nPAIR_HARNESS_DIALOGUE_API_KEY=secret\nPAIR_HARNESS_DIALOGUE_MODEL=model\n"
        ));
        assert!(!env_content_has_real_config("PAIR_HARNESS_DEMO=1\n"));
        assert!(!env_content_has_real_config(
            "PAIR_HARNESS_DIALOGUE_BASE_URL=https://example.test\nPAIR_HARNESS_DIALOGUE_API_KEY=replace-with-your-api-key\nPAIR_HARNESS_DIALOGUE_MODEL=model\n"
        ));
    }
}
