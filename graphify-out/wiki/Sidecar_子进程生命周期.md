# Sidecar 子进程生命周期

> 9 nodes · cohesion 0.28

## Key Concepts

- **KillOnCloseJob** (7 connections) — `desktop/src-tauri/src/lib.rs`
- **.assign()** (6 connections) — `desktop/src-tauri/src/lib.rs`
- **SidecarProcess** (5 connections) — `desktop/src-tauri/src/lib.rs`
- **Child** (3 connections)
- **closing_the_job_kills_processes_inside_it()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **.drop()** (3 connections) — `desktop/src-tauri/src/lib.rs`
- **Drop** (1 connections)
- **HANDLE** (1 connections)
- **Send** (1 connections)

## Relationships

- [退出分类与重连退避](退出分类与重连退避.md) (4 shared connections)
- [Sidecar 进程重连管理](Sidecar_进程重连管理.md) (3 shared connections)
- [Sidecar 启动装配](Sidecar_启动装配.md) (2 shared connections)
- [Sidecar 日志轮转](Sidecar_日志轮转.md) (1 shared connections)

## Source Files

- `desktop/src-tauri/src/lib.rs`

## Audit Trail

- EXTRACTED: 20 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*