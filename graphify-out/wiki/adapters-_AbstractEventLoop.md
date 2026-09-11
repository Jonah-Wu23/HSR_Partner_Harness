# adapters: AbstractEventLoop

> 10 nodes · cohesion 0.33

## Key Concepts

- **._run_synthesis()** (12 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **_TtsBridgeEvent** (5 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **_put()** (4 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **on_complete()** (3 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **on_data()** (3 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **on_error()** (3 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`
- **AbstractEventLoop** (1 connections)
- **Event** (1 connections)
- **Queue** (1 connections)
- **executor 线程：提交文本 → 发 finish request → 等 FINISHED → 收尾。 真实服务在收到 finish…** (1 connections) — `src/pair_harness/adapters/audio/qwen_tts.py`

## Relationships

- [千问语音合成适配器](千问语音合成适配器.md) (4 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_tts.py`

## Audit Trail

- EXTRACTED: 19 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*