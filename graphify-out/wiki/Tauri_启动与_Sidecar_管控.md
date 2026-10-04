# Tauri 启动与 Sidecar 管控

> 8 nodes · cohesion 0.29

## Key Concepts

- **encode_request_line()** (8 connections) — `desktop/src-tauri/src/lib.rs`
- **forwarded_sidecar_flags()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **run()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **stop_backend()** (4 connections) — `desktop/src-tauri/src/lib.rs`
- **debug_console_requested()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **request_line_is_single_json_line()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **I** (2 connections)
- **Vec** (2 connections)

## Relationships

- [退出分类与重连退避](退出分类与重连退避.md) (7 shared connections)
- [Sidecar 进程重连管理](Sidecar_进程重连管理.md) (4 shared connections)
- [聊天窗口创建与标题](聊天窗口创建与标题.md) (2 shared connections)
- [Sidecar 日志轮转](Sidecar_日志轮转.md) (1 shared connections)
- [Sidecar 启动装配](Sidecar_启动装配.md) (1 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 23 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*