# desktop_backend: DiagnosticCallback

> 19 nodes · cohesion 0.15

## Key Concepts

- **engine_factory.py** (27 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **build_coding_engine()** (21 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **ProviderKind** (9 connections) — `src/pair_harness/config/providers.py`
- **_reasonix_config_toml()** (6 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_reasonix_api_key_env()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **resolve_reasonix_executable()** (5 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_resolve_executable()** (3 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **_toml_quote()** (3 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **Enum** (2 connections)
- **_provider_env()** (2 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **DiagnosticCallback** (1 connections)
- **str** (1 connections)
- **编程助手引擎工厂——V0.2 M3（方案 §M3-4/§M3-5）。 B-03（V0.3.9）：产品只支持 OpenAI Chat Completions…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **TOML basic string 严格转义，防止引号/换行/反斜杠破坏配置。** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **可执行文件：打包内置 > 环境变量 > PATH 默认名。** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **reasonix 可执行文件（DeepSeek 编程助手）。 Tauri 侧发现内置二进制后经…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **为任意 OpenAI Chat Completions 兼容端点构建编程助手引擎。 B-03：产品只有 reasonix ACP…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **``api_key_env`` 指向的变量名（Reasonix 从 ``<REASONIX_HOME>/.env`` 取值）。 DeepSeek 端点沿用既有…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`
- **``REASONIX_HOME/config.toml`` 正文：一个 OpenAI 兼容供应商实例。 依据（本机 Reasonix 二进制内嵌文档 §3.1…** (1 connections) — `src/pair_harness/desktop_backend/engine_factory.py`

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (17 shared connections)
- [desktop_backend: _atomic_write_text…](desktop_backend-__atomic_write_text….md) (7 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (4 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (3 shared connections)
- [子进程启动与终止](子进程启动与终止.md) (3 shared connections)
- [test_v038_t4_delegation_chain.py: _FakeCodexAuth](test_v038_t4_delegation_chain.py-__FakeCodexAuth.md) (3 shared connections)
- [Codex 鉴权服务](Codex_鉴权服务.md) (2 shared connections)
- [V0.3.8 委派执行链测试](V0.3.8_委派执行链测试.md) (1 shared connections)
- [语音运行时接线](语音运行时接线.md) (1 shared connections)
- [repro_full_flow.py: repro_full_flow.py](repro_full_flow.py-_repro_full_flow.py.md) (1 shared connections)

## Source Files

- `src/pair_harness/config/providers.py`
- `src/pair_harness/desktop_backend/engine_factory.py`

## Audit Trail

- EXTRACTED: 59 (88%)
- INFERRED: 8 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*