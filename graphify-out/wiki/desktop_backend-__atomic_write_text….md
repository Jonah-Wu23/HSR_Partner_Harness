# desktop_backend: _atomic_write_text…

> 14 nodes · cohesion 0.22

## Key Concepts

- **ensure_reasonix_home()** (17 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **test_engine_factory.py** (6 connections) — `tests/unit/test_engine_factory.py`
- **_normalize_reasonix_effort()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **test_reasonix_home_strictly_escapes_toml_and_writes_atomic_env()** (5 connections) — `tests/unit/test_engine_factory.py`
- **_atomic_write_text()** (4 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **Path** (4 connections)
- **test_reasonix_home_exposes_only_execution_tools()** (4 connections) — `tests/unit/test_engine_factory.py`
- **test_reasonix_home_normalizes_unsupported_effort_to_auto()** (4 connections) — `tests/unit/test_engine_factory.py`
- **test_reasonix_home_writes_configured_supported_effort()** (4 connections) — `tests/unit/test_engine_factory.py`
- **Path** (2 connections)
- **同目录临时文件写入后原子替换（.env/config.toml 共用）。** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **把角色模型配置的档位归一化为 Reasonix 支持的 effort 值。 Reasonix 的 provider ``effort`` 接受…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **为账号准备 reasonix 配置目录（``REASONIX_HOME/config.toml`` + ``.env``）。 reasonix…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **M3.3：含引号/反斜杠/换行的配置不能破坏 TOML；.env 原子替换无残留。** (1 connections) — `tests/unit/test_engine_factory.py`

## Relationships

- [desktop_backend: DiagnosticCallback](desktop_backend-_DiagnosticCallback.md) (7 shared connections)
- [Codex 鉴权服务](Codex_鉴权服务.md) (5 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (4 shared connections)
- [test_v038_t4_delegation_chain.py: _FakeCodexAuth](test_v038_t4_delegation_chain.py-__FakeCodexAuth.md) (2 shared connections)
- [子进程启动与终止](子进程启动与终止.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/engine_factory.py`
- `tests/unit/test_engine_factory.py`

## Audit Trail

- EXTRACTED: 34 (87%)
- INFERRED: 5 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*