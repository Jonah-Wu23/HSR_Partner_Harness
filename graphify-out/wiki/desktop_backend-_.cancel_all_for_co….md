# desktop_backend: .cancel_all_for_co…

> 4 nodes · cohesion 0.50

## Key Concepts

- **.cancel_all_for_connection()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.cancel_session()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **静默取消（连接断开/错误路径）：清理会话，不发任何事件。 幂等：未知 ``session_id`` 直接返回。取消会向识别器发流结束哨兵，…** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **取消某连接的全部会话（连接断开时调用；幂等，不发事件）。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`

## Relationships

- [移动端音频与 ASR 会话](移动端音频与_ASR_会话.md) (2 shared connections)

## Source Files

- `src/pair_harness/desktop_backend/mobile_audio.py`

## Audit Trail

- EXTRACTED: 5 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*