# OpenAI 兼容层测试

> 39 nodes · cohesion 0.11

## Key Concepts

- **test_openai_compatible.py** (27 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_logs_non_deepseek_endpoint_retry_block()** (13 connections) — `tests/unit/test_openai_compatible.py`
- **_user_message()** (13 connections) — `tests/unit/test_openai_compatible.py`
- **handler()** (12 connections) — `tests/unit/test_openai_compatible.py`
- **_deepseek_model()** (11 connections) — `tests/unit/test_openai_compatible.py`
- **asyncio** (11 connections)
- **test_generate_title_uses_assistant_only_non_streaming_request()** (11 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_does_not_retry_when_speech_already_streamed()** (11 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_logs_blocked_retry_reason_when_attempts_exhausted()** (11 connections) — `tests/unit/test_openai_compatible.py`
- **_stream_transport()** (10 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_carries_memory_from_delegation_retry()** (10 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_carries_memory_from_retried_attempt()** (10 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_logs_empty_output_retry_and_final_source()** (10 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_retries_empty_output_then_raises_bounded()** (9 connections) — `tests/unit/test_openai_compatible.py`
- **test_stream_reply_recovers_after_truncated_json_retry()** (8 connections) — `tests/unit/test_openai_compatible.py`
- **_info_messages()** (7 connections) — `tests/unit/test_openai_compatible.py`
- **MockTransport** (5 connections)
- **_mock_stream_transport()** (4 connections) — `tests/unit/test_openai_compatible.py`
- **test_public_parse_output_keeps_empty_body_failure()** (2 connections) — `tests/unit/test_openai_compatible.py`
- **LogCaptureFixture** (1 connections)
- **DeepSeek 结构化端点持续空输出：有界重试后仍失败才报「输出为空」。 不合成结果：三次真实请求后直接抛错（初始 + 2 次有界重试）。** (1 connections) — `tests/unit/test_openai_compatible.py`
- **首次输出 JSON 截断、尚无 speech 增量时，对有界重试后的正常结果放行。** (1 connections) — `tests/unit/test_openai_compatible.py`
- **按请求顺序返回 content 分片的 SSE 传输（每次请求取一项）。** (1 connections) — `tests/unit/test_openai_compatible.py`
- **空输出后重试成功：INFO 必须记下不可用输出、重试与最终来源。 第一次真实请求返回纯空白（A02 证据里的形状），第二次返回可用 JSON。…** (1 connections) — `tests/unit/test_openai_compatible.py`
- **重试耗尽：两次重试各留一条 INFO，最后一次说明不再重试的原因。** (1 connections) — `tests/unit/test_openai_compatible.py`
- *... and 14 more nodes in this community*

## Relationships

- [对话上下文与消息模型](对话上下文与消息模型.md) (17 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (12 shared connections)
- [模型输出解析](模型输出解析.md) (10 shared connections)
- [test_deepseek_request_shape.py: AsyncClient](test_deepseek_request_shape.py-_AsyncClient.md) (3 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [test_openai_compatible.py: 公开解析入口（Codex 适配器共用…](test_openai_compatible.py-_公开解析入口（Codex_适配器共用….md) (1 shared connections)

## Source Files

- `tests/unit/test_openai_compatible.py`

## Audit Trail

- EXTRACTED: 96 (74%)
- INFERRED: 34 (26%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*