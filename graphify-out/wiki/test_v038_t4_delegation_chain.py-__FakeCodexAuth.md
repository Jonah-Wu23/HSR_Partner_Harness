# test_v038_t4_delegation_chain.py: _FakeCodexAuth

> 15 nodes · cohesion 0.13

## Key Concepts

- **_FakeCodexAuth** (7 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **test_acp_engine_forwards_diagnostic_callback()** (5 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **test_compatible_endpoint_assembles_acp_engine_without_responses_check()** (5 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **test_compatible_endpoint_is_written_into_reasonix_config()** (5 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **test_deepseek_endpoint_keeps_proven_reasonix_config()** (5 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **test_openai_official_endpoint_also_assembles_acp_engine()** (5 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **Path** (3 connections)
- **.__init__()** (2 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **.env_overrides()** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **DeepSeek 端点保持既有（真机已通过）的 Reasonix 配置形态不变。** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **诊断回调从装配方透传到 ACP 引擎（契约 §14.6）。** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **build_coding_engine 只需要 base_dir/account_id 与 env_overrides。** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **任意 http(s) 兼容端点（含不可解析域名）都装配 AcpCodingEngine。 B-03：不再有 Responses 校验，也不再有 Codex…** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **OpenAI 官方端点同样走 ACP 引擎（不存在 codex app-server 分支）。** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`
- **通用端点必须真的写入 Reasonix 配置，而不是删掉校验后仍走别的引擎。 依据（本机 reasonix 二进制内嵌文档 §3.1）：``kind =…** (1 connections) — `tests/unit/test_v038_t4_delegation_chain.py`

## Relationships

- [V0.3.8 委派执行链测试](V0.3.8_委派执行链测试.md) (6 shared connections)
- [desktop_backend: DiagnosticCallback](desktop_backend-_DiagnosticCallback.md) (3 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (3 shared connections)
- [desktop_backend: _atomic_write_text…](desktop_backend-__atomic_write_text….md) (2 shared connections)
- [Codex 鉴权服务](Codex_鉴权服务.md) (2 shared connections)

## Source Files

- `tests/unit/test_v038_t4_delegation_chain.py`

## Audit Trail

- EXTRACTED: 25 (83%)
- INFERRED: 5 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*