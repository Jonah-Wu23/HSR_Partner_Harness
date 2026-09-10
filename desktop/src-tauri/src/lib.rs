// 桌面二进制入口在 src/main.rs；应用主体（含移动端 mobile_entry_point 的 run()）在本库。

use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

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

/// stderr 日志单文件上限：达到上限后在下一次会话开始时滚动，
/// 避免同一文件跨批次无限追加（V039-S4-010）。
const SIDECAR_LOG_MAX_BYTES: u64 = 4 * 1024 * 1024;
/// 保留的滚动副本数量（sidecar.stderr.log.1 … .N）。
const SIDECAR_LOG_BACKUPS: u32 = 3;

fn sidecar_log_backup_path(path: &Path, index: u32) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(format!(".{index}"));
    PathBuf::from(name)
}

/// 日志达到 max_bytes 时把当前文件滚动为 .1，旧副本依次后移，最旧的丢弃。
/// 文件不存在或未达上限时不做改动；backups 至少为 1。返回是否发生滚动。
fn rotate_sidecar_log(path: &Path, max_bytes: u64, backups: u32) -> std::io::Result<bool> {
    let size = match std::fs::metadata(path) {
        Ok(metadata) => metadata.len(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    if size < max_bytes {
        return Ok(false);
    }
    let oldest = sidecar_log_backup_path(path, backups);
    if oldest.exists() {
        std::fs::remove_file(&oldest)?;
    }
    for index in (1..backups).rev() {
        let from = sidecar_log_backup_path(path, index);
        if from.exists() {
            std::fs::rename(&from, sidecar_log_backup_path(path, index + 1))?;
        }
    }
    std::fs::rename(path, sidecar_log_backup_path(path, 1))?;
    Ok(true)
}

/// 会话起始标记：日志跨会话追加时，凭这一行把后续日志归属到具体会话与进程。
fn sidecar_log_session_header(
    stream_id: u64,
    pid: u32,
    mode: BackendMode,
    timestamp: &str,
) -> String {
    format!(
        "===== sidecar stderr session {timestamp} stream_id={stream_id} pid={pid} mode={} =====\n",
        mode.as_str()
    )
}

/// 日志时间戳取 UTC（带 Z 后缀），避免跨批次比对时依赖本机时区。
fn utc_timestamp(now: SystemTime) -> String {
    let elapsed = now.duration_since(UNIX_EPOCH).unwrap_or(Duration::ZERO);
    let seconds = elapsed.as_secs();
    let (year, month, day) = civil_from_days((seconds / 86_400) as i64);
    let second_of_day = seconds % 86_400;
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{:03}Z",
        second_of_day / 3_600,
        (second_of_day % 3_600) / 60,
        second_of_day % 60,
        elapsed.subsec_millis(),
    )
}

/// 以 1970-01-01 为第 0 天的日序 → (年, 月, 日)。
/// Howard Hinnant 的 civil_from_days，避免为一个时间戳引入新依赖。
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_index = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_index + 2) / 5 + 1) as u32;
    let month = if month_index < 10 {
        month_index + 3
    } else {
        month_index - 9
    };
    let year = if month <= 2 { year + 1 } else { year };
    (year, month as u32, day)
}

/// 打开会话日志并写入起始标记：先按上限滚动，再追加本次会话的标记行。
fn open_sidecar_log(path: &Path, header: &str) -> std::io::Result<File> {
    rotate_sidecar_log(path, SIDECAR_LOG_MAX_BYTES, SIDECAR_LOG_BACKUPS)?;
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;
    file.write_all(header.as_bytes())?;
    file.flush()?;
    Ok(file)
}

/// 打开本次会话的日志；打不开时说明原因并放弃落盘，但不中断 stderr 排空。
fn open_session_log(log_path: Option<PathBuf>, header: &str) -> Option<File> {
    let Some(path) = log_path else {
        eprintln!("[sidecar] 应用数据目录不可用，stderr 不落盘");
        return None;
    };
    match open_sidecar_log(&path, header) {
        Ok(file) => Some(file),
        Err(error) => {
            eprintln!("[sidecar] stderr 日志不可写（{}）：{error}", path.display());
            None
        }
    }
}

fn drain_sidecar_stderr(stderr: ChildStderr, log_path: Option<PathBuf>, header: String) {
    std::thread::spawn(move || {
        let mut log = open_session_log(log_path, &header);
        let mut reader = BufReader::new(stderr);
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

/// 手机远程 WS 服务器端口。必须与前端 `RemotePairingPanel` 二维码 payload
/// 中的 ws 端口保持一致；sidecar 侧端口被占时降级为桌面专用并上报
/// `serve_start_failed`（见 `desktop_backend/__main__.py`）。
const REMOTE_SERVE_PORT: &str = "8765";

fn pwa_static_dir(
    packaged: bool,
    resource_root: Option<&Path>,
    runtime_root: &Path,
) -> Option<PathBuf> {
    if packaged {
        let root = resource_root?;
        for base in [root, &root.join("resources")] {
            let candidate = base.join("mobile-dist");
            if candidate.is_dir() {
                return Some(candidate);
            }
        }
        return None;
    }
    let candidate = runtime_root.join("desktop").join("mobile").join("dist");
    candidate.is_dir().then_some(candidate)
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

/// Sidecar 运行模式。真实模式是默认值；演示模式只能由显式请求触发
/// （V039-S4-002：缺少 .env 时不得静默降级为演示数据）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BackendMode {
    Real,
    Demo,
}

impl BackendMode {
    /// 传给 Sidecar 的命令行开关。
    fn as_arg(self) -> &'static str {
        match self {
            BackendMode::Real => "--real",
            BackendMode::Demo => "--demo",
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            BackendMode::Real => "real",
            BackendMode::Demo => "demo",
        }
    }
}

/// PAIR_HARNESS_REAL 的取值 → 模式；反向取值同样是显式声明，指向另一个模式。
fn mode_from_real_flag(value: bool) -> BackendMode {
    if value {
        BackendMode::Real
    } else {
        BackendMode::Demo
    }
}

/// PAIR_HARNESS_DEMO 的取值 → 模式。
fn mode_from_demo_flag(value: bool) -> BackendMode {
    if value {
        BackendMode::Demo
    } else {
        BackendMode::Real
    }
}

/// 合并同一来源里的一对模式声明：都没声明得到 None；两条声明指向不同模式时报错，
/// 不静默取其一。
fn merge_mode_flags(real: Option<bool>, demo: Option<bool>) -> Result<Option<BackendMode>, String> {
    let from_real = real.map(mode_from_real_flag);
    let from_demo = demo.map(mode_from_demo_flag);
    match (from_real, from_demo) {
        (Some(left), Some(right)) if left != right => Err(format!(
            "配置冲突：PAIR_HARNESS_REAL 与 PAIR_HARNESS_DEMO 指向不同模式（{} / {}）",
            left.as_str(),
            right.as_str()
        )),
        (Some(mode), _) | (_, Some(mode)) => Ok(Some(mode)),
        (None, None) => Ok(None),
    }
}

/// 命令行显式请求；命令行是最高优先级来源。
fn cli_mode_request<I>(args: I) -> Result<Option<BackendMode>, String>
where
    I: IntoIterator<Item = String>,
{
    let mut real = false;
    let mut demo = false;
    for arg in args {
        match arg.as_str() {
            "--real" => real = true,
            "--demo" => demo = true,
            _ => {}
        }
    }
    merge_mode_flags(real.then_some(true), demo.then_some(true))
}

/// 进程环境变量里的显式请求。
fn env_mode_request() -> Result<Option<BackendMode>, String> {
    merge_mode_flags(env_flag("PAIR_HARNESS_REAL"), env_flag("PAIR_HARNESS_DEMO"))
}

/// .env 内容里的显式请求。对话配置（BASE_URL/API_KEY/MODEL）是否齐全不再参与
/// 模式判定：缺配置必须由真实模式如实报错，而不是降级成演示数据。
fn env_content_mode_request(contents: &str) -> Result<Option<BackendMode>, String> {
    merge_mode_flags(
        env_content_flag(contents, "PAIR_HARNESS_REAL"),
        env_content_flag(contents, "PAIR_HARNESS_DEMO"),
    )
}

/// 读取 .env 里的显式请求；文件不存在等同没有声明，读取失败如实报错。
fn env_file_mode_request(path: Option<&Path>) -> Result<Option<BackendMode>, String> {
    let Some(path) = path else {
        return Ok(None);
    };
    match std::fs::read_to_string(path) {
        Ok(contents) => env_content_mode_request(&contents),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("读取 {} 失败：{error}", path.display())),
    }
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

/// 模式判定优先级：命令行 > 进程环境 > .env；三者都没有声明时默认真实模式。
fn resolve_backend_mode(
    cli: Option<BackendMode>,
    env: Option<BackendMode>,
    file: Option<BackendMode>,
) -> BackendMode {
    cli.or(env).or(file).unwrap_or(BackendMode::Real)
}

/// 从当前进程的实参、环境变量与已定位到的 .env 解析 Sidecar 模式。
fn detect_backend_mode(env_file: Option<&Path>) -> Result<BackendMode, String> {
    Ok(resolve_backend_mode(
        cli_mode_request(std::env::args())?,
        env_mode_request()?,
        env_file_mode_request(env_file)?,
    ))
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
    let mode = detect_backend_mode(env_file.as_deref())?;
    let stderr_log = sidecar_stderr_log_path(app);
    let mut command = Command::new(program);
    command.current_dir(&runtime_root);
    if packaged.is_some() {
        command
            .arg(mode.as_arg())
            .arg("--serve")
            .arg(REMOTE_SERVE_PORT)
            .arg("--project")
            .arg(&initial_project_root);
    } else {
        command
            .args([
                "-m",
                "pair_harness.desktop_backend",
                mode.as_arg(),
                "--serve",
                REMOTE_SERVE_PORT,
                "--project",
            ])
            .arg(&initial_project_root);
    }
    command.env("PAIR_HARNESS_STREAM_ID", stream_id.to_string());
    if let Some(pwa_dir) = pwa_static_dir(
        packaged.is_some(),
        app.path().resource_dir().ok().as_deref(),
        &runtime_root,
    ) {
        command.env("PAIR_HARNESS_PWA_DIR", pwa_dir);
    }
    if let Some(env_file) = env_file {
        command.env("PAIR_HARNESS_ENV_FILE", env_file);
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
        let header = sidecar_log_session_header(
            stream_id,
            child.id(),
            mode,
            &utc_timestamp(SystemTime::now()),
        );
        drain_sidecar_stderr(stderr, stderr_log, header);
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
    let Some(conversation) = value
        .get("payload")
        .and_then(|payload| payload.get("conversation"))
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
        // V0.3.7 契约 §9.2：Android 壳本地通知（任务完成/委派结果/审批请求
        // 三类事件的壳内本地通知走此插件；桌面端注册但无 JS 调用方）。
        .plugin(tauri_plugin_notification::init())
        .setup(move |app| {
            // V0.3.7 契约 §9.1：Android 壳不运行 Python Sidecar（移动端无法承载）。
            // 壳内前端加载 desktop/mobile 同一产物，经 wsClient 直连桌面端 --serve 的
            // WS 通道，配对/鉴权与事件协议完全复用；desktop_request 等桌面命令在
            // 移动目标下无 Sidecar 可用（state 未注册，try_state 返回 None）。
            #[cfg(mobile)]
            {
                let _ = &debug_console; // 移动端不启动 Sidecar，调试开关仅作用于桌面目标
            }
            #[cfg(desktop)]
            {
                let state = spawn_backend(app.handle(), debug_console)?;
                app.manage(state);
            }
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
            if let tauri::RunEvent::ExitRequested {
                code: None,
                ref api,
                ..
            } = event
            {
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

#[cfg(test)]
mod tests {
    use super::{
        backoff_delay, civil_from_days, classify_exit, cli_mode_request, debug_console_requested,
        encode_request_line, env_content_mode_request, env_file_mode_request, fail_pending,
        open_sidecar_log, pwa_static_dir, request_timeout_secs, resolve_backend_mode,
        rotate_sidecar_log, sidecar_log_backup_path, sidecar_log_session_header, stream_id_value,
        utc_timestamp, BackendMode, ExitClass, PendingMap, REMOTE_SERVE_PORT,
    };
    use serde_json::json;
    use std::collections::HashMap;
    use std::io::Write;
    use std::process::ExitStatus;
    use std::sync::{Arc, Mutex};
    use std::time::{Duration, UNIX_EPOCH};

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
            segments
                .iter()
                .map(|segment| segment.len())
                .collect::<Vec<_>>(),
            vec![8, 4, 4, 4, 12]
        );
        assert!(segments[2].starts_with('4'));
        assert!(matches!(
            segments[3].chars().next(),
            Some('8') | Some('9') | Some('a') | Some('b')
        ));
        assert!(first.chars().all(|ch| ch.is_ascii_hexdigit() || ch == '-'));
    }

    // ------------------------------------------------- V039-S4-002 后端模式判定

    #[test]
    fn backend_mode_defaults_to_real_without_any_explicit_request() {
        // 无 .env、无 --demo、无模式环境变量时必须是真实模式，不得静默跑演示数据
        assert_eq!(resolve_backend_mode(None, None, None), BackendMode::Real);
    }

    #[test]
    fn higher_priority_explicit_request_wins() {
        assert_eq!(
            resolve_backend_mode(
                Some(BackendMode::Demo),
                Some(BackendMode::Real),
                Some(BackendMode::Real)
            ),
            BackendMode::Demo
        );
        assert_eq!(
            resolve_backend_mode(None, Some(BackendMode::Demo), Some(BackendMode::Real)),
            BackendMode::Demo
        );
        assert_eq!(
            resolve_backend_mode(None, None, Some(BackendMode::Demo)),
            BackendMode::Demo
        );
    }

    #[test]
    fn demo_mode_requires_an_explicit_command_line_flag() {
        assert_eq!(
            cli_mode_request(["--demo".to_string()]).unwrap(),
            Some(BackendMode::Demo)
        );
        assert_eq!(
            cli_mode_request(["--real".to_string()]).unwrap(),
            Some(BackendMode::Real)
        );
        assert_eq!(
            cli_mode_request(["hsr-partner-harness.exe".to_string()]).unwrap(),
            None
        );
        // 同一来源里两条相反声明必须暴露为冲突，不能静默取其一
        assert!(cli_mode_request(["--demo".to_string(), "--real".to_string()]).is_err());
    }

    #[test]
    fn dialogue_config_alone_is_not_a_mode_declaration() {
        // 只有对话配置、没有任何模式声明：不算显式请求（旧实现据此降级为演示）
        assert_eq!(env_content_mode_request("PAIR_HARNESS_DIALOGUE_BASE_URL=https://example.test\nPAIR_HARNESS_DIALOGUE_API_KEY=secret\nPAIR_HARNESS_DIALOGUE_MODEL=model\n").unwrap(), None);
        assert_eq!(env_content_mode_request("# 没有模式声明\n").unwrap(), None);
        assert_eq!(
            env_content_mode_request("PAIR_HARNESS_DEMO=1\n").unwrap(),
            Some(BackendMode::Demo)
        );
        assert_eq!(
            env_content_mode_request("PAIR_HARNESS_REAL=1\n").unwrap(),
            Some(BackendMode::Real)
        );
        // 反向取值同样是显式声明，指向另一个模式
        assert_eq!(
            env_content_mode_request("PAIR_HARNESS_REAL=0\n").unwrap(),
            Some(BackendMode::Demo)
        );
        assert_eq!(
            env_content_mode_request("PAIR_HARNESS_DEMO=0\n").unwrap(),
            Some(BackendMode::Real)
        );
        assert!(env_content_mode_request("PAIR_HARNESS_REAL=1\nPAIR_HARNESS_DEMO=1\n").is_err());
    }

    #[test]
    fn missing_env_file_is_not_a_demo_signal() {
        let base = std::env::temp_dir().join(format!("ph-env-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let env_file = base.join(".env");

        assert_eq!(env_file_mode_request(None).unwrap(), None);
        assert_eq!(env_file_mode_request(Some(&env_file)).unwrap(), None);

        std::fs::write(&env_file, "PAIR_HARNESS_DEMO=1\n").unwrap();
        assert_eq!(
            env_file_mode_request(Some(&env_file)).unwrap(),
            Some(BackendMode::Demo)
        );
        std::fs::write(&env_file, "PAIR_HARNESS_DIALOGUE_MODEL=deepseek-chat\n").unwrap();
        assert_eq!(env_file_mode_request(Some(&env_file)).unwrap(), None);

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn remote_serve_port_matches_frontend_qrcode_payload() {
        // 前端 RemotePairingPanel 的二维码 payload 硬编码同一端口，改动需两侧同步。
        assert_eq!(REMOTE_SERVE_PORT, "8765");
    }

    #[test]
    fn pwa_static_dir_resolves_dev_dist_and_packaged_resource() {
        let base = std::env::temp_dir().join(format!("ph-pwa-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);

        // dev：仓库 desktop/mobile/dist 存在时注入
        let dev_dist = base
            .join("repo")
            .join("desktop")
            .join("mobile")
            .join("dist");
        std::fs::create_dir_all(&dev_dist).unwrap();
        assert_eq!(
            pwa_static_dir(false, None, &base.join("repo")),
            Some(dev_dist)
        );
        // dev：目录不存在不注入（sidecar / 返回 404，如实暴露）
        assert_eq!(pwa_static_dir(false, None, &base.join("repo-none")), None);

        // packaged：resource 根或 resources/ 下的 mobile-dist
        let pkg_root = base.join("pkg");
        let pkg_dist = pkg_root.join("resources").join("mobile-dist");
        std::fs::create_dir_all(&pkg_dist).unwrap();
        assert_eq!(
            pwa_static_dir(true, Some(&pkg_root), &base.join("repo")),
            Some(pkg_dist)
        );
        // packaged 资源缺失时不回落 dev 目录
        assert_eq!(
            pwa_static_dir(true, Some(&base.join("pkg-empty")), &base.join("repo")),
            None
        );

        let _ = std::fs::remove_dir_all(&base);
    }

    // ------------------------------------------------- V039-S4-010 stderr 日志取证

    #[test]
    fn session_header_marks_stream_process_and_mode() {
        assert_eq!(
            sidecar_log_session_header(7, 4242, BackendMode::Real, "2026-09-10T10:37:00.000Z"),
            "===== sidecar stderr session 2026-09-10T10:37:00.000Z stream_id=7 pid=4242 mode=real =====\n"
        );
        assert!(sidecar_log_session_header(8, 1, BackendMode::Demo, "T").contains("mode=demo"));
    }

    #[test]
    fn utc_timestamp_matches_unix_epoch_seconds() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(20_454), (2026, 1, 1));
        assert_eq!(
            utc_timestamp(UNIX_EPOCH + Duration::from_secs(1_789_036_620)),
            "2026-09-10T10:37:00.000Z"
        );
        assert_eq!(
            utc_timestamp(UNIX_EPOCH + Duration::from_millis(1_789_036_620_123)),
            "2026-09-10T10:37:00.123Z"
        );
    }

    #[test]
    fn log_rotates_into_numbered_backups_when_over_the_limit() {
        let base = std::env::temp_dir().join(format!("ph-log-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let log = base.join("sidecar.stderr.log");
        let backup = |index: u32| sidecar_log_backup_path(&log, index);

        // 文件不存在或未达上限：不滚动，也不报错
        assert!(!rotate_sidecar_log(&log, 8, 2).unwrap());
        std::fs::write(&log, b"first").unwrap();
        assert!(!rotate_sidecar_log(&log, 8, 2).unwrap());
        assert!(log.exists());

        // 达到上限：当前日志变成 .1
        assert!(rotate_sidecar_log(&log, 5, 2).unwrap());
        assert!(!log.exists());
        assert_eq!(std::fs::read(backup(1)).unwrap(), b"first");

        // 再滚动两次：旧副本后移，最旧的按上限丢弃
        std::fs::write(&log, b"second").unwrap();
        assert!(rotate_sidecar_log(&log, 5, 2).unwrap());
        assert_eq!(std::fs::read(backup(1)).unwrap(), b"second");
        assert_eq!(std::fs::read(backup(2)).unwrap(), b"first");
        std::fs::write(&log, b"third").unwrap();
        assert!(rotate_sidecar_log(&log, 5, 2).unwrap());
        assert_eq!(std::fs::read(backup(1)).unwrap(), b"third");
        assert_eq!(std::fs::read(backup(2)).unwrap(), b"second");
        assert!(!backup(3).exists());

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn opening_the_log_writes_one_session_marker_per_session() {
        let base = std::env::temp_dir().join(format!("ph-log-open-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir_all(&base).unwrap();
        let log = base.join("sidecar.stderr.log");

        for (index, mode) in [(1u64, BackendMode::Real), (2u64, BackendMode::Demo)] {
            let header = sidecar_log_session_header(index, 100 + index as u32, mode, "T");
            let mut file = open_sidecar_log(&log, &header).unwrap();
            file.write_all(format!("body-{index}\n").as_bytes())
                .unwrap();
        }

        let expected = concat!(
            "===== sidecar stderr session T stream_id=1 pid=101 mode=real =====\n",
            "body-1\n",
            "===== sidecar stderr session T stream_id=2 pid=102 mode=demo =====\n",
            "body-2\n",
        );
        assert_eq!(std::fs::read_to_string(&log).unwrap(), expected);

        let _ = std::fs::remove_dir_all(&base);
    }
}
