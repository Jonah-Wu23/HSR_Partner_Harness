# test_codex_transport_robustness.py: test_codex_transpo…

> 10 nodes · cohesion 0.33

## Key Concepts

- **test_codex_transport_robustness.py** (8 connections) — `tests/integration/test_codex_transport_robustness.py`
- **make_transport()** (7 connections) — `tests/integration/test_codex_transport_robustness.py`
- **asyncio** (4 connections)
- **test_bad_json_line_is_skipped_and_loop_continues()** (4 connections) — `tests/integration/test_codex_transport_robustness.py`
- **test_constructor_request_timeout_applies_by_default()** (4 connections) — `tests/integration/test_codex_transport_robustness.py`
- **test_request_timeout_raises_recognizable_error()** (4 connections) — `tests/integration/test_codex_transport_robustness.py`
- **factory()** (1 connections) — `tests/integration/test_codex_transport_robustness.py`
- **O1.3：读循环遇到坏 JSON 行只跳过，后续正常响应仍被解析。** (1 connections) — `tests/integration/test_codex_transport_robustness.py`
- **O1.3：服务端不响应时请求超时，抛出可识别异常。** (1 connections) — `tests/integration/test_codex_transport_robustness.py`
- **O1.3：构造级 request_timeout 作为默认超时生效。** (1 connections) — `tests/integration/test_codex_transport_robustness.py`

## Relationships

- [Codex 传输集成测试](Codex_传输集成测试.md) (2 shared connections)
- [JSONL 子进程传输](JSONL_子进程传输.md) (2 shared connections)
- [Codex 审批流集成测试](Codex_审批流集成测试.md) (1 shared connections)

## Source Files

- `tests/integration/test_codex_transport_robustness.py`

## Audit Trail

- EXTRACTED: 19 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*