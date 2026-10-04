# 手机端 ASR 会话测试

> 21 nodes · cohesion 0.18

## Key Concepts

- **test_mobile_audio.py** (38 connections) — `tests/unit/test_mobile_audio.py`
- **FakeRecognizer** (11 connections) — `tests/unit/test_mobile_audio.py`
- **b64()** (10 connections) — `tests/unit/test_mobile_audio.py`
- **test_cancel_all_for_connection_is_silent_and_scoped()** (6 connections) — `tests/unit/test_mobile_audio.py`
- **s()** (5 connections) — `tests/unit/test_asr_merge.py`
- **test_lifecycle_start_feed_end_returns_final()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_partial_callbacks_emitted()** (5 connections) — `tests/unit/test_mobile_audio.py`
- **test_asr_error_surfaces_as_voice_asr_failed()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_cancel_then_feed_raises_not_found()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_empty_final_returned_as_empty_string()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_parallel_conversations_are_independent()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_seq_gap_raises_with_expected_and_actual()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_unknown_session_raises()** (4 connections) — `tests/unit/test_mobile_audio.py`
- **test_duplicate_start_same_conversation_rejected()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **test_invalid_base64_raises()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_duplicate_begin_raises()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_feed_monotonic_seq_and_roundtrip()** (3 connections) — `tests/unit/test_mobile_audio.py`
- **.stream_transcribe()** (2 connections) — `tests/unit/test_mobile_audio.py`
- **test_sequencer_finish_releases_only_its_own_handle()** (2 connections) — `tests/unit/test_mobile_audio.py`
- **.__init__()** (1 connections) — `tests/unit/test_mobile_audio.py`
- **识别器端口替身，经 recognizer_factory 注入会话管理器。 ``partials`` 在消费每个分片后按序产出；流结束后按…** (1 connections) — `tests/unit/test_mobile_audio.py`

## Relationships

- [手机 ASR 会话管理器](手机_ASR_会话管理器.md) (11 shared connections)
- [手机语音分片会话协议](手机语音分片会话协议.md) (8 shared connections)
- [手机 PTT 语音往返测试](手机_PTT_语音往返测试.md) (6 shared connections)
- [并发与自动摘要测试](并发与自动摘要测试.md) (5 shared connections)
- [手机端 TTS 分片编目](手机端_TTS_分片编目.md) (4 shared connections)
- [角色卡绑定与命令测试](角色卡绑定与命令测试.md) (3 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (3 shared connections)
- [Sidecar JSONL 协议路由](Sidecar_JSONL_协议路由.md) (3 shared connections)
- [ASR 句子归并](ASR_句子归并.md) (1 shared connections)
- [DashScope 任务脚本](DashScope_任务脚本.md) (1 shared connections)
- [手机音频转写会话](手机音频转写会话.md) (1 shared connections)
- [DashScope 模拟服务端](DashScope_模拟服务端.md) (1 shared connections)

## Source Files

- `tests/unit/test_asr_merge.py`
- `tests/unit/test_mobile_audio.py`

## Audit Trail

- EXTRACTED: 58 (68%)
- INFERRED: 27 (32%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*