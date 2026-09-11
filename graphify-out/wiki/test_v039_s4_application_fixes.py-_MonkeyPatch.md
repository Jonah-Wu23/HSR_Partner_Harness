# test_v039_s4_application_fixes.py: MonkeyPatch

> 12 nodes · cohesion 0.17

## Key Concepts

- **test_mobile_tts_begin_failure_is_reported_not_swallowed()** (16 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **test_mobile_tts_preemption_is_not_reported_as_failure()** (13 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **MonkeyPatch** (3 connections)
- **explode()** (2 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **V039-S4-018 收尾：begin 抛错必须走同一失败上报路径，不再无人观察地结束。** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **V039-S4-018：抢占/停止是正常控制流，不得广播 voice.mobile_tts_failed。** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **aclose()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **__init__()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **synthesize()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **aclose()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **__init__()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`
- **synthesize()** (1 connections) — `tests/unit/test_v039_s4_application_fixes.py`

## Relationships

- [对话上下文与消息模型](对话上下文与消息模型.md) (10 shared connections)
- [桌面协议编解码测试](桌面协议编解码测试.md) (6 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (2 shared connections)
- [移动端音频与 ASR 会话](移动端音频与_ASR_会话.md) (2 shared connections)

## Source Files

- `tests/unit/test_v039_s4_application_fixes.py`

## Audit Trail

- EXTRACTED: 18 (58%)
- INFERRED: 13 (42%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*