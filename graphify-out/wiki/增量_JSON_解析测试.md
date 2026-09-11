# 增量 JSON 解析测试

> 22 nodes · cohesion 0.16

## Key Concepts

- **test_incremental_json.py** (15 connections) — `tests/unit/test_incremental_json.py`
- **make_request()** (9 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_emits_reasoning_lifecycle_events()** (8 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_yields_clean_speech_deltas_and_raw_completed()** (8 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_plain_text_falls_back_to_raw_deltas()** (7 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_rejects_truncated_json_tail()** (7 connections) — `tests/unit/test_incremental_json.py`
- **reasoning_stream_transport()** (6 connections) — `tests/unit/test_incremental_json.py`
- **stream_transport()** (6 connections) — `tests/unit/test_incremental_json.py`
- **json_delta_chunks()** (5 connections) — `tests/unit/test_incremental_json.py`
- **asyncio** (4 connections)
- **test_parser_no_speech_key_extracts_nothing_but_keeps_raw()** (4 connections) — `tests/unit/test_incremental_json.py`
- **MockTransport** (2 connections)
- **handler()** (2 connections) — `tests/unit/test_incremental_json.py`
- **V0.2 M2：增量 JSON 解析器与对话流式事件序列（问题 10）。 - speech.delta 只含干净台词（不再闪烁 JSON 键名/引号）； -…** (1 connections) — `tests/unit/test_incremental_json.py`
- **裸裁决 JSON（无 speech 字段）：不上屏增量，完整输出留待 review 复用。** (1 connections) — `tests/unit/test_incremental_json.py`
- **JSON 流：speech.delta 只含干净台词；speech.completed 携带完整 raw。** (1 connections) — `tests/unit/test_incremental_json.py`
- **reasoning_content 走独立通道：started → delta → completed。** (1 connections) — `tests/unit/test_incremental_json.py`
- **非 JSON 输出：整段作为台词增量，final 台词一致。** (1 connections) — `tests/unit/test_incremental_json.py`
- **JSON 收尾截断时直接失败，不能把增量预览当成完整协议结果。** (1 connections) — `tests/unit/test_incremental_json.py`
- **把 JSON 对象序列化为 SSE content 分片序列（可指定切分粒度）。** (1 connections) — `tests/unit/test_incremental_json.py`
- **同时带 reasoning_content（仅首个分片）与 content 的流。** (1 connections) — `tests/unit/test_incremental_json.py`
- **handler()** (1 connections) — `tests/unit/test_incremental_json.py`

## Relationships

- [Codex 对话模型](Codex_对话模型.md) (5 shared connections)
- [adapters: incremental_json.p…](adapters-_incremental_json.p….md) (4 shared connections)
- [test_deepseek_request_shape.py: AsyncClient](test_deepseek_request_shape.py-_AsyncClient.md) (4 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)

## Source Files

- `tests/unit/test_incremental_json.py`

## Audit Trail

- EXTRACTED: 41 (75%)
- INFERRED: 14 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*