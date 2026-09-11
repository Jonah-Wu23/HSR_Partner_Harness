# adapters: AcpCodec

> 16 nodes · cohesion 0.20

## Key Concepts

- **AcpCodec** (15 connections) — `src/pair_harness/adapters/acp/engine.py`
- **.map_notification()** (8 connections) — `src/pair_harness/adapters/acp/engine.py`
- **Any** (6 connections)
- **._op_fields()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._text_of()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._tool_text()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **._usage_number()** (4 connections) — `src/pair_harness/adapters/acp/engine.py`
- **test_codec_failed_tool_carries_command_and_stderr()** (4 connections) — `tests/unit/test_acp_engine.py`
- **._next()** (2 connections) — `src/pair_harness/adapters/acp/engine.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **ACP 通知 → EngineEvent 映射（reasonix v1.24 实测形状）。 reasonix 把消息/思考/工具/计划统一封装为…** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **message/thought chunk 的纯文本。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **从 usage 对象里取第一个存在的整数 token 值；无则返回 None（不估算）。** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **tool_call_update 的 content（结果文本）提取。 兼容 dict / 文本数组两种形状；失败型工具可能携带 stderr/error/…** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **从 tool_call / request_permission 的 rawInput 提取门控字段。 映射到编排器 PendingOperation…** (1 connections) — `src/pair_harness/adapters/acp/engine.py`
- **V0.3.3：失败工具回执附带命令摘要与 stderr/error 文本，诊断不再 只有退出码（真实 Reasonix 失败只给 "command…** (1 connections) — `tests/unit/test_acp_engine.py`

## Relationships

- [ACP 编码引擎](ACP_编码引擎.md) (6 shared connections)
- [V0.3.9 指标与诊断测试](V0.3.9_指标与诊断测试.md) (2 shared connections)
- [adapters: ._ensure_initializ…](adapters-_._ensure_initializ….md) (1 shared connections)
- [ACP 引擎测试](ACP_引擎测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/acp/engine.py`
- `tests/unit/test_acp_engine.py`

## Audit Trail

- EXTRACTED: 28 (82%)
- INFERRED: 6 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*