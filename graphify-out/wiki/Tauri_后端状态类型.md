# Tauri 后端状态类型

> 31 nodes · cohesion 0.11

## Key Concepts

- **BackendState** (26 connections) — `desktop/src-tauri/src/lib.rs`
- **start_reader()** (11 connections) — `desktop/src-tauri/src/lib.rs`
- **spawn_backend()** (10 connections) — `desktop/src-tauri/src/lib.rs`
- **desktop_request()** (9 connections) — `desktop/src-tauri/src/lib.rs`
- **Arc** (8 connections)
- **.reconnect_loop()** (8 connections) — `desktop/src-tauri/src/lib.rs`
- **sidecar_reconnect()** (8 connections) — `desktop/src-tauri/src/lib.rs`
- **.respawn()** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **.ensure_reconnect_loop()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **sync_chat_window_titles()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **Value** (5 connections)
- **fail_pending()** (4 connections) — `desktop/src-tauri/src/lib.rs`
- **ChildStdout** (3 connections)
- **.publish_disconnected()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **backoff_delay()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **next_stream_id()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **REQUEST_TIMEOUT_SECS** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **State** (3 connections)
- **Child** (2 connections)
- **ChildStdin** (2 connections)
- **.publish_connected()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **disconnected_sidecar_releases_pending_request()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **HashMap** (2 connections)
- **PendingMap** (2 connections)
- **Self** (2 connections)
- *... and 6 more nodes in this community*

## Relationships

- [Tauri 后端重连与退避](Tauri_后端重连与退避.md) (17 shared connections)
- [src: chat_window_title(…](src-_chat_window_title….md) (10 shared connections)
- [Tauri 边车启动与日志](Tauri_边车启动与日志.md) (7 shared connections)
- [src: BackendMode](src-_BackendMode.md) (6 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 93 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*