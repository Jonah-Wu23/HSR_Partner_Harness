# Sidecar 启动装配

> 14 nodes · cohesion 0.32

## Key Concepts

- **launch_sidecar()** (20 connections) — `desktop/src-tauri/src/lib.rs`
- **Option** (10 connections)
- **PathBuf** (10 connections)
- **AppHandle** (7 connections)
- **drain_sidecar_stderr()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **configured_env_file()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **open_session_log()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **packaged_reasonix()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **packaged_sidecar()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **pwa_static_dir()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_stderr_log_path()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **python_command()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **repository_root()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **ChildStderr** (1 connections)

## Relationships

- [退出分类与重连退避](退出分类与重连退避.md) (12 shared connections)
- [Sidecar 进程重连管理](Sidecar_进程重连管理.md) (8 shared connections)
- [Sidecar 日志轮转](Sidecar_日志轮转.md) (7 shared connections)
- [聊天窗口创建与标题](聊天窗口创建与标题.md) (5 shared connections)
- [Sidecar 子进程生命周期](Sidecar_子进程生命周期.md) (2 shared connections)
- [Tauri 启动与 Sidecar 管控](Tauri_启动与_Sidecar_管控.md) (1 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 64 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*