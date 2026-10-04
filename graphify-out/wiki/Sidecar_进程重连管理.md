# Sidecar 进程重连管理

> 24 nodes · cohesion 0.17

## Key Concepts

- **BackendState** (24 connections) — `desktop/src-tauri/src/lib.rs`
- **start_reader()** (12 connections) — `desktop/src-tauri/src/lib.rs`
- **desktop_request()** (10 connections) — `desktop/src-tauri/src/lib.rs`
- **spawn_backend()** (10 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_reconnect()** (9 connections) — `desktop/src-tauri/src/lib.rs`
- **Arc** (8 connections)
- **.reconnect_loop()** (8 connections) — `desktop/src-tauri/src/lib.rs`
- **.respawn()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **.ensure_reconnect_loop()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **sync_chat_window_titles()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **fail_pending()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **Value** (4 connections)
- **ChildStdout** (3 connections)
- **.publish_disconnected()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **next_stream_id()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **Self** (3 connections)
- **ChildStdin** (2 connections)
- **.publish_connected()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **disconnected_sidecar_releases_pending_request()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **HashMap** (2 connections)
- **PendingMap** (2 connections)
- **AtomicBool** (1 connections)
- **Mutex** (1 connections)
- **Sender** (1 connections)

## Relationships

- [退出分类与重连退避](退出分类与重连退避.md) (12 shared connections)
- [聊天窗口创建与标题](聊天窗口创建与标题.md) (11 shared connections)
- [Sidecar 启动装配](Sidecar_启动装配.md) (8 shared connections)
- [Tauri 启动与 Sidecar 管控](Tauri_启动与_Sidecar_管控.md) (4 shared connections)
- [Sidecar 日志轮转](Sidecar_日志轮转.md) (4 shared connections)
- [Sidecar 子进程生命周期](Sidecar_子进程生命周期.md) (3 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 88 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*