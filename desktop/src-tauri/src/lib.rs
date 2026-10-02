// 桌面二进制入口在 src/main.rs；应用主体（含移动端 mobile_entry_point 的 run()）在本库。

use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use percent_encoding::{utf8_percent_encode, AsciiSet, NON_ALPHANUMERIC};
use serde_json::{json, Value};
use tauri::{Emitter, Manager, State};
use time::macros::format_description;
use time::OffsetDateTime;

type PendingMap = Arc<Mutex<HashMap<String, tokio::sync::oneshot::Sender<Value>>>>;

/// Windows 作业对象：句柄关闭时结束作业内全部进程。Sidecar 拉起的
/// cloudflared、reasonix 自动进入同一作业，Sidecar 被强杀或崩溃后不会遗留。
#[cfg(windows)]
mod sidecar_job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    pub struct KillOnCloseJob(HANDLE);

    // 句柄只由持有它的 SidecarProcess 移动和关闭。
    unsafe impl Send for KillOnCloseJob {}

    impl KillOnCloseJob {
        /// 新建 KILL_ON_JOB_CLOSE 作业并把 `child` 放进去。
        pub fn assign(child: &Child) -> std::io::Result<Self> {
            // SAFETY: 传入的指针均指向有效的局部值或为空，句柄由 Self 独占并在 Drop 关闭。
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return Err(std::io::Error::last_os_error());
                }
                let job = Self(handle);
                let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    &info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION
                        as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                ) == 0
                {
                    return Err(std::io::Error::last_os_error());
                }
                if AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE) == 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(job)
            }
        }
    }

    impl Drop for KillOnCloseJob {
        fn drop(&mut self) {
            // SAFETY: 句柄由 CreateJobObjectW 返回且只在这里关闭一次。
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

/// Sidecar 子进程。Windows 下连同作业对象一起持有：整体丢弃时作业句柄关闭，
/// Sidecar 及其仍在运行的子进程随之结束。
struct SidecarProcess {
    child: Child,
    #[cfg(windows)]
    _job: sidecar_job::KillOnCloseJob,
}

/// 独立聊天窗口归属的会话，会话改名时据此同步窗口标题。
#[derive(Debug, Clone)]
struct ChatWindowMeta {
    conversation_id: String,
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
    child: Mutex<Option<SidecarProcess>>,
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
    /// 独立聊天窗口登记表：窗口 label 到会话元数据。
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

/// URL query 组件编码集：A-Za-z0-9 与 -_.~ 原样保留，其余字节按百分号编码。
const QUERY_COMPONENT: &AsciiSet = &NON_ALPHANUMERIC
    .remove(b'-')
    .remove(b'_')
    .remove(b'.')
    .remove(b'~');

fn encode_query_component(value: &str) -> String {
    utf8_percent_encode(value, QUERY_COMPONENT).to_string()
}

/// 聊天窗口标题：会话名加应用名。
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

/// stderr 日志单文件上限：达到上限后在下一次会话开始时滚动，避免同一文件无限追加。
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
fn sidecar_log_session_header(stream_id: u64, pid: u32, timestamp: &str) -> String {
    format!("===== sidecar stderr session {timestamp} stream_id={stream_id} pid={pid} =====\n")
}

/// 日志时间戳取 UTC 并带 Z 后缀，不受本机时区影响。
fn utc_timestamp(now: SystemTime) -> String {
    let format =
        format_description!("[year]-[month]-[day]T[hour]:[minute]:[second].[subsecond digits:3]Z");
    OffsetDateTime::from(now)
        .format(format)
        .expect("格式描述是编译期常量，只用到 OffsetDateTime 具备的日期与时间分量")
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

/// 手机远程 WS 服务器端口，与前端 RemotePairingPanel 的缺省端口一致。
/// Sidecar 默认监听 127.0.0.1，开启局域网直连后监听 0.0.0.0；端口被占用时
/// Sidecar 只服务桌面端并上报 `serve_start_failed`（见 `desktop_backend/__main__.py`）。
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

/// Sidecar 读取的 .env 路径：设置了 PAIR_HARNESS_ENV_FILE 就用它，安装版用
/// %LOCALAPPDATA%\PairHarness\.env，源码运行用仓库根的 .env。文件不存在时
/// Sidecar 按未配置处理。
fn configured_env_file(packaged: bool) -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os("PAIR_HARNESS_ENV_FILE") {
        return Ok(PathBuf::from(value));
    }
    if packaged {
        let local_app_data = std::env::var_os("LOCALAPPDATA")
            .ok_or_else(|| "环境变量 LOCALAPPDATA 未设置，无法定位安装版的 .env".to_string())?;
        return Ok(PathBuf::from(local_app_data)
            .join("PairHarness")
            .join(".env"));
    }
    Ok(repository_root().join(".env"))
}

/// 按出现顺序挑出桌面进程实参里的模式与局域网直连开关，原样转发给 Sidecar。
/// Sidecar 负责检测冲突，并结合 PAIR_HARNESS_REAL、PAIR_HARNESS_DEMO、
/// PAIR_HARNESS_LAN 环境变量与 .env 决定运行模式和是否开启局域网直连。
fn forwarded_sidecar_flags<I>(args: I) -> Vec<String>
where
    I: IntoIterator<Item = String>,
{
    args.into_iter()
        .skip(1)
        .filter(|arg| matches!(arg.as_str(), "--real" | "--demo" | "--lan" | "--no-lan"))
        .collect()
}

fn stream_id_value(stream_id: u64) -> String {
    stream_id.to_string()
}

/// 拉起一个 Sidecar 进程并取回它的 stdin/stdout 句柄，读取线程由调用方启动。
///
/// 每次启动使用调用方传入的新 `stream_id`，经环境变量交给 Python，事件按代次隔离。
/// `runtime_root` 是进程工作目录，`initial_project_root` 是首次启动的默认项目根，
/// 位于可写的 app_data_dir。
fn launch_sidecar(
    app: &tauri::AppHandle,
    debug_console: bool,
    stream_id: u64,
) -> Result<(SidecarProcess, ChildStdin, ChildStdout), String> {
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
    let env_file = configured_env_file(packaged.is_some())?;
    let stderr_log = sidecar_stderr_log_path(app);
    let mut command = Command::new(program);
    command.current_dir(&runtime_root);
    if packaged.is_none() {
        command.args(["-m", "pair_harness.desktop_backend"]);
    }
    command
        .args(forwarded_sidecar_flags(std::env::args()))
        .arg("--serve")
        .arg(REMOTE_SERVE_PORT)
        .arg("--project")
        .arg(&initial_project_root);
    command.env("PAIR_HARNESS_STREAM_ID", stream_id.to_string());
    command.env("PAIR_HARNESS_ENV_FILE", env_file);
    if let Some(pwa_dir) = pwa_static_dir(
        packaged.is_some(),
        app.path().resource_dir().ok().as_deref(),
        &runtime_root,
    ) {
        command.env("PAIR_HARNESS_PWA_DIR", pwa_dir);
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
    #[cfg(windows)]
    let job = match sidecar_job::KillOnCloseJob::assign(&child) {
        Ok(job) => job,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("为 Python Sidecar 建立作业对象失败：{error}"));
        }
    };
    if let Some(stderr) = child.stderr.take() {
        let header =
            sidecar_log_session_header(stream_id, child.id(), &utc_timestamp(SystemTime::now()));
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
    let process = SidecarProcess {
        child,
        #[cfg(windows)]
        _job: job,
    };
    Ok((process, stdin, stdout))
}

impl BackendState {
    /// 断开广播：connection.status disconnected，再发一条 recoverable 的 error.reported。
    fn publish_disconnected(&self, message: &str) {
        let stream_id = *self.current_stream_id.lock().unwrap();
        let _ = self.connection.send(false);
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "connection.status",
                "stream_id": stream_id_value(stream_id),
                "payload": {"status": "disconnected", "stream_id": stream_id_value(stream_id)}
            }),
        );
        let _ = self.app.emit(
            "sidecar://event",
            json!({
                "kind": "event",
                "event": "error.reported",
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
                "stream_id": stream_id_value(stream_id),
                "payload": {"status": "connected", "stream_id": stream_id_value(stream_id)}
            }),
        );
    }

    /// 重新拉起 Sidecar：成功后新旧 stdin/child 已交换，失败返回原因。
    fn respawn(&self) -> Result<ChildStdout, String> {
        let stream_id = next_stream_id();
        let (process, stdin, stdout) = launch_sidecar(&self.app, self.debug_console, stream_id)?;
        *self.current_stream_id.lock().unwrap() = stream_id;
        *self.stdin.lock().unwrap() = Some(stdin);
        *self.child.lock().unwrap() = Some(process);
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
    let (process, stdin, stdout) = launch_sidecar(app, debug_console, stream_id)?;
    let (connection, _) = tokio::sync::watch::channel(true);
    let state = Arc::new(BackendState {
        app: app.clone(),
        debug_console,
        child: Mutex::new(Some(process)),
        stdin: Mutex::new(Some(stdin)),
        pending: Arc::new(Mutex::new(HashMap::new())),
        current_stream_id: Mutex::new(stream_id),
        shutdown: AtomicBool::new(false),
        reconnecting: AtomicBool::new(false),
        connection,
        last_error: Mutex::new(None),
        crash_streak: Mutex::new(0),
        chat_windows: Mutex::new(HashMap::new()),
    });
    start_reader(&state, stdout, stream_id);
    Ok(state)
}

/// 读取线程：把 Sidecar 的 stdout JSONL 转发为 sidecar://event，EOF 时按退出原因处理。
///
/// 每个读取线程绑定自己的 `stream_id`。当前代次换成新进程后，旧 reader 立即退出，
/// 不转发迟到事件，也不会把新连接标成 disconnected。
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
                        "stream_id": stream_id_value(stream_id),
                        "payload": {"code": "invalid_sidecar_json", "message": "Sidecar 输出不是合法 JSON"}
                    }),
                );
                continue;
            };
            if *state.current_stream_id.lock().unwrap() != stream_id {
                break;
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
                sync_chat_window_titles(&state, &value);
                let _ = state.app.emit("sidecar://event", value);
            }
        }
        // EOF：只有当前代次的 reader 才能清 pending、取退出状态和广播。
        if *state.current_stream_id.lock().unwrap() != stream_id {
            return;
        }
        fail_pending(&state.pending, "Python Sidecar 已断开");
        // 取出的 SidecarProcess 在本语句结束时丢弃，作业对象随之结束遗留子进程。
        let exit_status = state
            .child
            .lock()
            .unwrap()
            .take()
            .and_then(|mut process| process.child.wait().ok());
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

/// conversation.changed 事件到达时，更新所有打开该会话的独立聊天窗口标题；
/// 标签栏标题由前端各自消费事件更新。
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

/// 把桌面请求转发给 Sidecar 并等待对应响应。`timeout_secs` 为 Some(n) 时最多等 n 秒；
/// 为 None 时一直等到 Sidecar 回复，Sidecar 断开时由 `fail_pending` 释放等待方。
#[tauri::command(rename_all = "snake_case")]
async fn desktop_request(
    request: Value,
    timeout_secs: Option<u64>,
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

    // 阻塞的 stdin 写入放到 blocking 线程池执行，事件循环不会被管道写入卡住。
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
    // 手动重连先把当前连接状态置为 false，再启动新代次，
    // 不能读取旧 watch 值提前返回成功。
    let _ = state.connection.send(false);
    // 让旧 reader 立刻失效，防止其迟到的 EOF 覆盖新连接状态。
    *state.current_stream_id.lock().unwrap() = u64::MAX;
    // 手动重连重置退避：即使此前连续崩溃，也立即尝试一次
    *state.crash_streak.lock().unwrap() = 0;
    // 强制终止现有进程（若有），由恢复循环立即重启。
    if let Some(mut process) = state.child.lock().unwrap().take() {
        let _ = process.child.kill();
        let _ = process.child.wait();
    }
    let _ = state.stdin.lock().unwrap().take();
    // 旧 reader 已失效，EOF 时不会再清理挂起请求，这里立即释放等待方。
    fail_pending(&state.pending, "Python Sidecar 已断开，正在重连");
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

/// 打开独立聊天窗口。
///
/// - 每次调用创建新的 WebviewWindow，label 为 `chat-{uuid}`，同一聊天可以开多个窗口。
/// - 窗口 URL 携带编码后的 conversation_id 与新 view_id，React 启动后调用
///   conversation.open 装载该聊天。
/// - 新窗口与主窗口共享同一个 Rust BackendState、Python Sidecar 与事件广播。
#[tauri::command(rename_all = "snake_case")]
async fn open_chat_window(
    app: tauri::AppHandle,
    state: State<'_, Arc<BackendState>>,
    conversation_id: String,
    title: String,
) -> Result<String, String> {
    let window_id = uuid::Uuid::new_v4().to_string();
    let view_id = uuid::Uuid::new_v4().to_string();
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
    state
        .chat_windows
        .lock()
        .unwrap()
        .insert(label.clone(), ChatWindowMeta { conversation_id });
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
    if let Some(mut process) = state.child.lock().unwrap().take() {
        // 先给 Python 有限时间优雅退出，超时再强制结束；process 丢弃时
        // 作业对象结束仍在运行的子进程。
        loop {
            if let Ok(Some(_status)) = process.child.try_wait() {
                break;
            }
            if Instant::now() >= deadline {
                let _ = process.child.kill();
                let _ = process.child.wait();
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
        // Android 壳用它发送任务完成、委派结果与审批请求的本地通知；桌面前端不调用。
        .plugin(tauri_plugin_notification::init())
        .setup(move |app| {
            // Android 壳不运行 Python Sidecar。壳内前端加载 desktop/mobile 的同一产物，
            // 经 wsClient 连接桌面端 --serve 的 WS 通道，复用配对、鉴权与事件协议。
            // 移动目标不注册 BackendState，desktop_request 等桌面命令在这里不可用。
            #[cfg(mobile)]
            {
                let _ = &debug_console; // 调试开关只作用于桌面目标
            }
            #[cfg(desktop)]
            {
                let state = spawn_backend(app.handle(), debug_console)?;
                app.manage(state);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // 窗口销毁时从聊天窗口登记表移除。
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
            // 关闭聊天窗口只销毁该窗口。仍有窗口时拒绝退出请求，最后一个窗口
            // 关闭后才进入退出，并在 Exit 时停止 Sidecar。
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
        backoff_delay, classify_exit, debug_console_requested, encode_request_line, fail_pending,
        forwarded_sidecar_flags, open_sidecar_log, pwa_static_dir, rotate_sidecar_log,
        sidecar_log_backup_path, sidecar_log_session_header, stream_id_value, utc_timestamp,
        ExitClass, PendingMap, REMOTE_SERVE_PORT,
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

    #[cfg(windows)]
    #[test]
    fn closing_the_job_kills_processes_inside_it() {
        use super::sidecar_job::KillOnCloseJob;
        use std::process::{Command, Stdio};
        use std::time::Instant;

        let mut child = Command::new("ping")
            .args(["-n", "30", "127.0.0.1"])
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        let job = KillOnCloseJob::assign(&child).unwrap();
        assert!(child.try_wait().unwrap().is_none());

        drop(job);
        let deadline = Instant::now() + Duration::from_secs(5);
        let exited = loop {
            if child.try_wait().unwrap().is_some() {
                break true;
            }
            if Instant::now() >= deadline {
                break false;
            }
            std::thread::sleep(Duration::from_millis(20));
        };
        if !exited {
            let _ = child.kill();
        }
        assert!(exited, "关闭作业句柄后作业内进程应被结束");
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

    // ------------------------------------------------------------------ 退出分类与退避

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

    // ------------------------------------------------- 聊天窗口辅助

    #[test]
    fn query_component_encodes_reserved_characters() {
        use super::{chat_window_title, encode_query_component};
        assert_eq!(encode_query_component("conv-1"), "conv-1");
        assert_eq!(encode_query_component("a b&c=d"), "a%20b%26c%3Dd");
        assert_eq!(encode_query_component("中文"), "%E4%B8%AD%E6%96%87");
        assert_eq!(chat_window_title("奥赫玛"), "奥赫玛 · HSR Partner Harness");
    }

    #[test]
    fn sidecar_receives_mode_and_lan_flags_in_original_order() {
        let args = [
            "hsr-partner-harness.exe",
            "--debug-console",
            "--lan",
            "--demo",
            "--no-lan",
            "--real",
        ]
        .map(String::from);
        assert_eq!(
            forwarded_sidecar_flags(args),
            ["--lan", "--demo", "--no-lan", "--real"]
        );
        // argv[0] 是程序路径，不参与转发
        assert!(forwarded_sidecar_flags(["--real".to_string()]).is_empty());
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

    // ------------------------------------------------- stderr 日志

    #[test]
    fn session_header_marks_stream_and_process() {
        assert_eq!(
            sidecar_log_session_header(7, 4242, "2026-09-10T10:37:00.000Z"),
            "===== sidecar stderr session 2026-09-10T10:37:00.000Z stream_id=7 pid=4242 =====\n"
        );
    }

    #[test]
    fn utc_timestamp_matches_unix_epoch_seconds() {
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

        for index in [1u64, 2u64] {
            let header = sidecar_log_session_header(index, 100 + index as u32, "T");
            let mut file = open_sidecar_log(&log, &header).unwrap();
            file.write_all(format!("body-{index}\n").as_bytes())
                .unwrap();
        }

        let expected = concat!(
            "===== sidecar stderr session T stream_id=1 pid=101 =====\n",
            "body-1\n",
            "===== sidecar stderr session T stream_id=2 pid=102 =====\n",
            "body-2\n",
        );
        assert_eq!(std::fs::read_to_string(&log).unwrap(), expected);

        let _ = std::fs::remove_dir_all(&base);
    }
}
