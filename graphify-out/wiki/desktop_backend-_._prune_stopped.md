# desktop_backend: ._prune_stopped()

> 4 nodes · cohesion 0.50

## Key Concepts

- **._prune_stopped()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.stop()** (3 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **中断（``voice.mobile_tts_stop``）：标记条目已中断，不再接受 ``feed``。 幂等：未知 message_id…** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **限制“已中断”墓碑数量：超限后最早的按未知 message_id 处理。** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`

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