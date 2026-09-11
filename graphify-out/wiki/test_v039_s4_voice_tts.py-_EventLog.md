# test_v039_s4_voice_tts.py: EventLog

> 19 nodes · cohesion 0.12

## Key Concepts

- **service()** (14 connections) — `tests/unit/test_v035_wiring.py`
- **Any** (8 connections)
- **test_v039_s4_voice_tts.py** (8 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **EventLog** (7 connections) — `tests/unit/test_v035_wiring.py`
- **test_supplier_failure_is_still_reported()** (7 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **_install_relay_prerequisites()** (6 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **.__call__()** (2 connections) — `tests/unit/test_v035_wiring.py`
- **.payloads()** (2 connections) — `tests/unit/test_v035_wiring.py`
- **.__init__()** (1 connections) — `tests/unit/test_v035_wiring.py`
- **fixture** (1 connections)
- **事件订阅器（event_sink）：按事件名过滤 payload。** (1 connections) — `tests/unit/test_v035_wiring.py`
- **has_remote_subscribers()** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **publish()** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **V0.3.9（S4）语音侧离线回归：V039-S4-012（适配器侧）/ V039-S4-018（中继侧）。 本文件全部离线：DashScope…** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **V039-S4-018 反向断言：真实供应商失败仍必须上报失败事件。** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **让 _maybe_relay_mobile_tts 走到真实下发路径（无真实供应商）。** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **aclose()** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **__init__()** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`
- **synthesize()** (1 connections) — `tests/unit/test_v039_s4_voice_tts.py`

## Relationships

- [V0.3.5 接线测试](V0.3.5_接线测试.md) (10 shared connections)
- [V0.3.8 会话幂等测试](V0.3.8_会话幂等测试.md) (2 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (2 shared connections)
- [test_v039_s4_voice_tts.py: V039-S4-018：抢占旧合成不…](test_v039_s4_voice_tts.py-_V039-S4-018：抢占旧合成不….md) (2 shared connections)
- [test_v035_wiring.py: install_fake_qwen_…](test_v035_wiring.py-_install_fake_qwen_….md) (1 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (1 shared connections)
- [test_v035_codex_fixes.py: test_v035_codex_fi…](test_v035_codex_fixes.py-_test_v035_codex_fi….md) (1 shared connections)
- [test_v038_t2_device_mutex.py: test_v038_t2_devic…](test_v038_t2_device_mutex.py-_test_v038_t2_devic….md) (1 shared connections)
- [V0.3.8 委派执行链测试](V0.3.8_委派执行链测试.md) (1 shared connections)
- [Demo 语音合成](Demo_语音合成.md) (1 shared connections)
- [控制租约测试](控制租约测试.md) (1 shared connections)
- [审批终态测试](审批终态测试.md) (1 shared connections)

## Source Files

- `tests/unit/test_v035_wiring.py`
- `tests/unit/test_v039_s4_voice_tts.py`

## Audit Trail

- EXTRACTED: 44 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*