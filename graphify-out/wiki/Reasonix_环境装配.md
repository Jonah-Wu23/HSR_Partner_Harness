# Reasonix 环境装配

> 15 nodes · cohesion 0.21

## Key Concepts

- **engine_factory.py** (22 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **ensure_reasonix_home()** (15 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_normalize_reasonix_effort()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_reasonix_api_key_env()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_reasonix_config_toml()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_write_reasonix_env()** (4 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_atomic_write_text()** (3 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **Path** (3 connections)
- **_reasonix_executable()** (3 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **``.env`` 只放当前供应商的密钥变量；``value`` 为空时写空文件，内容未变时不改写。 值由 python-dotenv 的…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **把角色模型配置的档位归一化为 Reasonix 支持的 effort 值。 Reasonix 的 provider ``effort`` 接受…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **为账号准备 ``REASONIX_HOME``（``config.toml`` 与 ``.env``），返回目录。 Reasonix 只从…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **reasonix 可执行文件：打包版由 Tauri 经 PAIR_HARNESS_BUNDLED_REASONIX_BIN 注入， 源码运行可用…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **``api_key_env`` 指向的变量名；Reasonix 只从 ``<REASONIX_HOME>/.env`` 取它的值。** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **``REASONIX_HOME/config.toml`` 正文：一个 OpenAI 兼容供应商实例。 Reasonix 的 ``kind =…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`

## Relationships

- [供应商识别与推理档位](供应商识别与推理档位.md) (10 shared connections)
- [遗留登录与引擎装配](遗留登录与引擎装配.md) (8 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (4 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (2 shared connections)
- [JSONL JSON-RPC 传输](JSONL_JSON-RPC_传输.md) (1 shared connections)
- [子进程传输与进程回收](子进程传输与进程回收.md) (1 shared connections)
- [JSONL 连接协议抽象](JSONL_连接协议抽象.md) (1 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/engine_factory.py`

## Audit Trail

- EXTRACTED: 46 (94%)
- INFERRED: 3 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*