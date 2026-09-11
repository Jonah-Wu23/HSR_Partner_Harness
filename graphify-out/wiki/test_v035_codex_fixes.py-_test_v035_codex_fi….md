# test_v035_codex_fixes.py: test_v035_codex_fi…

> 16 nodes · cohesion 0.15

## Key Concepts

- **test_v035_codex_fixes.py** (11 connections) — `tests/unit/test_v035_codex_fixes.py`
- **test_mobile_tts_failure_publishes_failed_event()** (11 connections) — `tests/unit/test_v035_codex_fixes.py`
- **test_card_get_avatar_asset_corruption_raises()** (5 connections) — `tests/unit/test_v035_codex_fixes.py`
- **asyncio** (4 connections)
- **test_card_duplicate_copies_shared_assets()** (4 connections) — `tests/unit/test_v035_codex_fixes.py`
- **test_eventemitter_allocate_sequence_keeps_global_monotonic_order()** (3 connections) — `tests/unit/test_v035_codex_fixes.py`
- **V0.3.5 Codex Review 修复的回归测试（P1×6、P2×2 中的可离线验证项）。 覆盖： - Codex P1 #1：remote-only…** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **Codex P1 #1：remote-only 事件必须消费序号，与 emit 交错仍单调不重复。** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **Codex P1 #5：复制卡必须真实复制受管理资产；删除原卡后副本头像仍在。** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **Codex P1 #7：卡引用头像但资产文件损坏时如实失败，不合成 avatar:null。** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **Codex P1 #9：TTS 供应商失败必须发 voice.mobile_tts_failed，手机端不能停在 buffering。** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **aclose()** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **has_remote_subscribers()** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **__init__()** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **publish()** (1 connections) — `tests/unit/test_v035_codex_fixes.py`
- **synthesize()** (1 connections) — `tests/unit/test_v035_codex_fixes.py`

## Relationships

- [V0.3.8 会话幂等测试](V0.3.8_会话幂等测试.md) (3 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (3 shared connections)
- [test_v039_s4_voice_tts.py: EventLog](test_v039_s4_voice_tts.py-_EventLog.md) (1 shared connections)
- [委派与契约模型](委派与契约模型.md) (1 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (1 shared connections)
- [桌面后端角色卡命令](桌面后端角色卡命令.md) (1 shared connections)
- [审批代理](审批代理.md) (1 shared connections)

## Source Files

- `tests/unit/test_v035_codex_fixes.py`

## Audit Trail

- EXTRACTED: 25 (83%)
- INFERRED: 5 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*