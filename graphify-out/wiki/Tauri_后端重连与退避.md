# Tauri 后端重连与退避

> 39 nodes · cohesion 0.06

## Key Concepts

- **lib.rs** (85 connections) — `desktop/src-tauri/src/lib.rs`
- **encode_request_line()** (8 connections) — `desktop/src-tauri/src/lib.rs`
- **classify_exit()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **run()** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **configure_console()** (4 connections) — `desktop/src-tauri/src/lib.rs`
- **stop_backend()** (4 connections) — `desktop/src-tauri/src/lib.rs`
- **debug_console_requested()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **ExitClass** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **AllocConsole()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **FreeConsole()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **mode_from_demo_flag()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **mode_from_real_flag()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **request_line_is_single_json_line()** (2 connections) — `desktop/src-tauri/src/lib.rs`
- **ExitStatus** (2 connections)
- **I** (2 connections)
- **abnormal_exit_triggers_reconnect()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **backend_mode_defaults_to_real_without_any_explicit_request()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **BACKOFF_MAX_SECS** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **BACKOFF_START_SECS** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **backoff_starts_immediate_and_caps_at_max()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **clean_exit_without_shutdown_does_not_reconnect()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **debug_console_requires_explicit_flag()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **demo_mode_requires_an_explicit_command_line_flag()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **dialogue_config_alone_is_not_a_mode_declaration()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- **fatal_config_exit_code_stops_reconnect()** (1 connections) — `desktop/src-tauri/src/lib.rs`
- *... and 14 more nodes in this community*

## Relationships

- [Tauri 后端状态类型](Tauri_后端状态类型.md) (17 shared connections)
- [Tauri 边车启动与日志](Tauri_边车启动与日志.md) (17 shared connections)
- [src: BackendMode](src-_BackendMode.md) (16 shared connections)
- [src: chat_window_title(…](src-_chat_window_title….md) (10 shared connections)
- [子进程启动与终止](子进程启动与终止.md) (1 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 108 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*