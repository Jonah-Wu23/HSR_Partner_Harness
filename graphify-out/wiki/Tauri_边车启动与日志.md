# Tauri 边车启动与日志

> 22 nodes · cohesion 0.17

## Key Concepts

- **launch_sidecar()** (20 connections) — `desktop/src-tauri/src/lib.rs`
- **PathBuf** (10 connections)
- **AppHandle** (8 connections)
- **Path** (8 connections)
- **configured_env_file()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **drain_sidecar_stderr()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **open_sidecar_log()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **open_session_log()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **packaged_reasonix()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **packaged_sidecar()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **pwa_static_dir()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **rotate_sidecar_log()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_log_backup_path()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_log_session_header()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_stderr_log_path()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **opening_the_log_writes_one_session_marker_per_session()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **python_command()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **repository_root()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **.as_arg()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **log_rotates_into_numbered_backups_when_over_the_limit()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **File** (2 connections)
- **ChildStderr** (1 connections)

## Relationships

- [Tauri 后端重连与退避](Tauri_后端重连与退避.md) (17 shared connections)
- [src: BackendMode](src-_BackendMode.md) (15 shared connections)
- [Tauri 后端状态类型](Tauri_后端状态类型.md) (7 shared connections)
- [src: chat_window_title(…](src-_chat_window_title….md) (5 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 84 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*