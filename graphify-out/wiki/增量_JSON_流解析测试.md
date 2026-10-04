# 增量 JSON 流解析测试

> 19 nodes · cohesion 0.18

## Key Concepts

- **AsyncClient** (11 connections)
- **test_incremental_json.py** (11 connections) — `tests/unit/test_incremental_json.py`
- **make_request()** (8 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_emits_reasoning_lifecycle_events()** (8 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_rejects_truncated_json_tail()** (8 connections) — `tests/unit/test_incremental_json.py`
- **test_stream_yields_clean_speech_deltas_and_raw_completed()** (8 connections) — `tests/unit/test_incremental_json.py`
- **stream_transport()** (7 connections) — `tests/unit/test_incremental_json.py`
- **json_delta_chunks()** (5 connections) — `tests/unit/test_incremental_json.py`
- **test_parser_no_speech_key_extracts_nothing()** (4 connections) — `tests/unit/test_incremental_json.py`
- **asyncio** (3 connections)
- **handler()** (2 connections) — `tests/unit/test_incremental_json.py`
- **.chunks()** (2 connections) — `tests/voice_helpers.py`
- **MockTransport** (1 connections)
- **JSON 流：speech.delta 只含干净台词；speech.completed 携带完整 raw。** (1 connections) — `tests/unit/test_incremental_json.py`
- **reasoning_content 走独立通道：started → delta → completed。** (1 connections) — `tests/unit/test_incremental_json.py`
- **JSON 收尾截断时直接失败，不能把增量预览当成完整协议结果。** (1 connections) — `tests/unit/test_incremental_json.py`
- **把 JSON 对象序列化为 SSE content 分片序列（可指定切分粒度）。** (1 connections) — `tests/unit/test_incremental_json.py`
- **Chat Completions SSE 流；reasoning 非空时随首个分片下发 reasoning_content。** (1 connections) — `tests/unit/test_incremental_json.py`
- **裸裁决 JSON（无 speech 字段）：不上屏增量。** (1 connections) — `tests/unit/test_incremental_json.py`

## Relationships

- [OpenAI 兼容对话模型](OpenAI_兼容对话模型.md) (5 shared connections)
- [增量 JSON speech 解析](增量_JSON_speech_解析.md) (3 shared connections)
- [DeepSeek 请求体形状](DeepSeek_请求体形状.md) (2 shared connections)
- [角色回合输出解析测试](角色回合输出解析测试.md) (2 shared connections)
- [OpenAI 兼容对话解析](OpenAI_兼容对话解析.md) (2 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (2 shared connections)
- [对话适配器提示词解析](对话适配器提示词解析.md) (1 shared connections)
- [委派重试流式回放测试](委派重试流式回放测试.md) (1 shared connections)
- [演示模型与对话契约](演示模型与对话契约.md) (1 shared connections)
- [消息契约与会话编排](消息契约与会话编排.md) (1 shared connections)
- [CLI 入口与应用路径](CLI_入口与应用路径.md) (1 shared connections)
- [麦克风采集测试替身](麦克风采集测试替身.md) (1 shared connections)

## Source Files

- `tests/unit/test_incremental_json.py`
- `tests/voice_helpers.py`

## Audit Trail

- EXTRACTED: 34 (64%)
- INFERRED: 19 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*