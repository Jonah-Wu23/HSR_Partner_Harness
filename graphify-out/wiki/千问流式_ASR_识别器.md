# 千问流式 ASR 识别器

> 8 nodes · cohesion 0.32

## Key Concepts

- **QwenStreamingRecognizer** (16 connections) — `src/pair_harness/adapters/audio/qwen_asr.py`
- **test_partial_arrives_while_audio_is_still_streaming()** (7 connections) — `tests/unit/test_qwen_event_mapping.py`
- **collect()** (3 connections) — `tests/unit/test_qwen_event_mapping.py`
- **factory()** (2 connections) — `src/pair_harness/desktop_backend/application_service.py`
- **audio()** (2 connections) — `tests/unit/test_qwen_event_mapping.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/audio/qwen_asr.py`
- **qwen-audio-3.0-asr-flash-streaming 流式识别。 ``api_key`` / ``ws_url`` 缺省时沿用…** (1 connections) — `src/pair_harness/adapters/audio/qwen_asr.py`
- **script()** (1 connections) — `tests/unit/test_qwen_event_mapping.py`

## Relationships

- [千问语音合成与识别](千问语音合成与识别.md) (4 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (3 shared connections)
- [千问流式语音识别](千问流式语音识别.md) (2 shared connections)
- [千问事件映射测试](千问事件映射测试.md) (2 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (1 shared connections)
- [运行时装配与配置管理](运行时装配与配置管理.md) (1 shared connections)
- [千问识别事件映射测试](千问识别事件映射测试.md) (1 shared connections)
- [DashScope 任务脚本](DashScope_任务脚本.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_asr.py`
- `src/pair_harness/desktop_backend/application_service.py`
- `tests/unit/test_qwen_event_mapping.py`

## Audit Trail

- EXTRACTED: 16 (67%)
- INFERRED: 8 (33%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*