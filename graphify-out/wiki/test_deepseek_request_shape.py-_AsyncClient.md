# test_deepseek_request_shape.py: AsyncClient

> 18 nodes · cohesion 0.29

## Key Concepts

- **AsyncClient** (19 connections)
- **test_deepseek_request_shape.py** (12 connections) — `tests/unit/test_deepseek_request_shape.py`
- **make_request()** (12 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_deepseek_collaboration_retries_missing_delegation()** (9 connections) — `tests/unit/test_deepseek_request_shape.py`
- **_capturing_transport()** (8 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_deepseek_structured_dialogue_retries_empty_content_once()** (8 connections) — `tests/unit/test_deepseek_request_shape.py`
- **asyncio** (7 connections)
- **test_deepseek_structured_dialogue_uses_configured_sampling()** (7 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_deepseek_effort_medium_normalized_to_high()** (6 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_deepseek_structured_dialogue_disables_thinking()** (6 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_deepseek_thinking_disabled()** (6 connections) — `tests/unit/test_deepseek_request_shape.py`
- **test_non_deepseek_host_keeps_standard_body()** (6 connections) — `tests/unit/test_deepseek_request_shape.py`
- **handler()** (3 connections) — `tests/unit/test_deepseek_request_shape.py`
- **MockTransport** (3 connections)
- **B1：DeepSeek 请求体形态（离线，用 MockTransport 断言请求字段）。 验证 MVP 计划 §5 B1.1：识别…** (1 connections) — `tests/unit/test_deepseek_request_shape.py`
- **结构化角色回合按配置采样温度，不再固定为确定式采样。** (1 connections) — `tests/unit/test_deepseek_request_shape.py`
- **handler()** (1 connections) — `tests/unit/test_deepseek_request_shape.py`
- **handler()** (1 connections) — `tests/unit/test_deepseek_request_shape.py`

## Relationships

- [Codex 对话模型](Codex_对话模型.md) (9 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (6 shared connections)
- [增量 JSON 解析测试](增量_JSON_解析测试.md) (4 shared connections)
- [OpenAI 兼容层测试](OpenAI_兼容层测试.md) (3 shared connections)
- [模型输出解析](模型输出解析.md) (1 shared connections)
- [委派重试测试](委派重试测试.md) (1 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)

## Source Files

- `tests/unit/test_deepseek_request_shape.py`

## Audit Trail

- EXTRACTED: 40 (56%)
- INFERRED: 31 (44%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*