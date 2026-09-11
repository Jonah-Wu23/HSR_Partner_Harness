# Demo 语音合成

> 49 nodes · cohesion 0.08

## Key Concepts

- **SpeechRequest** (44 connections) — `src/pair_harness/core/contracts.py`
- **test_v039_l08_preemption.py** (29 connections) — `tests/unit/test_v039_l08_preemption.py`
- **AudioChunk** (19 connections) — `src/pair_harness/core/contracts.py`
- **test_assistant_and_tool_messages_never_preempt()** (15 connections) — `tests/unit/test_v039_l08_preemption.py`
- **FakePlayer** (15 connections) — `tests/unit/test_voice_runtime.py`
- **SpeechSynthesizer** (13 connections) — `src/pair_harness/core/ports.py`
- **audio/demo.py** (12 connections) — `src/pair_harness/adapters/audio/demo.py`
- **GatedSynthesizer** (11 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_interrupt_drops_inflight_pcm_and_reports_event()** (10 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_new_character_message_preempts_previous_speech()** (10 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_skip_playing_abandons_current_and_keeps_queue()** (10 connections) — `tests/unit/test_v039_l08_preemption.py`
- **audio.py** (9 connections) — `src/pair_harness/core/audio.py`
- **_runtime()** (9 connections) — `tests/unit/test_v039_l08_preemption.py`
- **_character_message()** (8 connections) — `tests/unit/test_v039_l08_preemption.py`
- **asyncio** (8 connections)
- **test_interrupt_without_activity_emits_nothing()** (7 connections) — `tests/unit/test_v039_l08_preemption.py`
- **DemoSpeechSynthesizer** (6 connections) — `src/pair_harness/adapters/audio/demo.py`
- **_pair_config()** (6 connections) — `tests/unit/test_v039_l08_preemption.py`
- **_stop_playback()** (6 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_chat_submit_interrupts_desktop_speech()** (5 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_remote_claim_interrupts_with_remote_reason()** (5 connections) — `tests/unit/test_v039_l08_preemption.py`
- **.synthesize()** (3 connections) — `src/pair_harness/adapters/audio/demo.py`
- **.synthesize()** (3 connections) — `src/pair_harness/core/ports.py`
- **.synthesize()** (3 connections) — `tests/unit/test_v039_l08_preemption.py`
- **test_speech_queue_interrupt_clears_and_drops_stale_items()** (3 connections) — `tests/unit/test_v039_l08_preemption.py`
- *... and 24 more nodes in this community*

## Relationships

- [语音运行时测试](语音运行时测试.md) (24 shared connections)
- [语音播放队列](语音播放队列.md) (14 shared connections)
- [千问语音合成适配器](千问语音合成适配器.md) (10 shared connections)
- [委派与契约模型](委派与契约模型.md) (7 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (7 shared connections)
- [对话上下文与消息模型](对话上下文与消息模型.md) (7 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (6 shared connections)
- [语音播放与采集控制](语音播放与采集控制.md) (5 shared connections)
- [Silero VAD 语音活动检测](Silero_VAD_语音活动检测.md) (4 shared connections)
- [adapters: DemoSpeechRecogniz…](adapters-_DemoSpeechRecogniz….md) (3 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (3 shared connections)
- [test_v039_l08_preemption.py: PreemptRecordingRu…](test_v039_l08_preemption.py-_PreemptRecordingRu….md) (3 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/demo.py`
- `src/pair_harness/core/audio.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `tests/unit/test_v039_l08_preemption.py`
- `tests/unit/test_voice_runtime.py`

## Audit Trail

- EXTRACTED: 163 (81%)
- INFERRED: 39 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*