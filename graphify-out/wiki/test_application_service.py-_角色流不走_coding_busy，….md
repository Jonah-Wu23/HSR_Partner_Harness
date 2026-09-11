# test_application_service.py: 角色流不走 coding busy，…

> 12 nodes · cohesion 0.14

## Key Concepts

- **test_role_turn_same_conversation_is_queued_while_streaming()** (11 connections) — `tests/unit/test_application_service.py`
- **test_busy_submit_enqueues_then_auto_dispatches_after_turn()** (8 connections) — `tests/unit/test_application_service.py`
- **test_chat_submit_registers_turn_with_lifecycle_events()** (8 connections) — `tests/unit/test_application_service.py`
- **角色流不走 coding busy，也必须阻止同一聊天并发生成两轮。** (1 connections) — `tests/unit/test_application_service.py`
- **V0.2 M2：一次提交 = 一个 Turn——提交返回 turn_id，后台推进 turn.started(running) →…** (1 connections) — `tests/unit/test_application_service.py`
- **V0.2 M2（问题 9）：忙碌时提交先入队返回 queue_item；回合完成后 自动派发队列项（成为真实用户消息），队列消费后清空。** (1 connections) — `tests/unit/test_application_service.py`
- **queued_text_dispatched()** (1 connections) — `tests/unit/test_application_service.py`
- **wait_for()** (1 connections) — `tests/unit/test_application_service.py`
- **turn_events()** (1 connections) — `tests/unit/test_application_service.py`
- **wait_for()** (1 connections) — `tests/unit/test_application_service.py`
- **generate_title()** (1 connections) — `tests/unit/test_application_service.py`
- **__init__()** (1 connections) — `tests/unit/test_application_service.py`

## Relationships

- [Demo 服务与队列测试](Demo_服务与队列测试.md) (12 shared connections)
- [语音试听声源校验测试](语音试听声源校验测试.md) (3 shared connections)
- [Codex 对话模型](Codex_对话模型.md) (2 shared connections)
- [规划式评审测试夹具](规划式评审测试夹具.md) (1 shared connections)

## Source Files

- `tests/unit/test_application_service.py`

## Audit Trail

- EXTRACTED: 24 (89%)
- INFERRED: 3 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*