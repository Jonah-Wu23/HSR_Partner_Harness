# 语音运行态 TTS 失败恢复

> 4 nodes · cohesion 0.50

## Key Concepts

- **test_tts_failure_reports_failed_then_recovers()** (9 connections) — `tests/unit/test_voice_runtime.py`
- **synthesize()** (2 connections) — `tests/unit/test_voice_runtime.py`
- **合成失败时 tts 置 failed 并清空待播队列，下一条消息按 synthesizing → playing → idle 恢复。** (1 connections) — `tests/unit/test_voice_runtime.py`
- **__init__()** (1 connections) — `tests/unit/test_voice_runtime.py`

## Relationships

- [语音播放与 VAD 测试](语音播放与_VAD_测试.md) (3 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (3 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (1 shared connections)

## Source Files

- `tests/unit/test_voice_runtime.py`

## Audit Trail

- EXTRACTED: 8 (80%)
- INFERRED: 2 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*