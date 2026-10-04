# Sidecar 日志轮转

> 9 nodes · cohesion 0.31

## Key Concepts

- **Result** (11 connections)
- **open_sidecar_log()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **rotate_sidecar_log()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **Path** (5 connections)
- **sidecar_log_backup_path()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_log_session_header()** (4 connections) — `desktop/src-tauri/src/lib.rs`
- **opening_the_log_writes_one_session_marker_per_session()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **log_rotates_into_numbered_backups_when_over_the_limit()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **File** (2 connections)

## Relationships

- [退出分类与重连退避](退出分类与重连退避.md) (7 shared connections)
- [Sidecar 启动装配](Sidecar_启动装配.md) (7 shared connections)
- [Sidecar 进程重连管理](Sidecar_进程重连管理.md) (4 shared connections)
- [聊天窗口创建与标题](聊天窗口创建与标题.md) (2 shared connections)
- [Tauri 启动与 Sidecar 管控](Tauri_启动与_Sidecar_管控.md) (1 shared connections)
- [Sidecar 子进程生命周期](Sidecar_子进程生命周期.md) (1 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 33 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*