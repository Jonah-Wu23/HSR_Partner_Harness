# Silero VAD 语音活动检测

> 54 nodes · cohesion 0.07

## Key Concepts

- **test_vad_state.py** (19 connections) — `tests/unit/test_vad_state.py`
- **VadEvent** (18 connections) — `src/pair_harness/core/contracts.py`
- **SileroVoiceActivityDetector** (15 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **_collect()** (14 connections) — `tests/unit/test_vad_state.py`
- **_make_detector()** (13 connections) — `tests/unit/test_vad_state.py`
- **VoiceActivityDetector** (12 connections) — `src/pair_harness/core/ports.py`
- **silero_vad.py** (9 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **VadUnavailableError** (7 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **FakeSession** (7 connections) — `tests/unit/test_vad_state.py`
- **DemoVoiceActivityDetector** (6 connections) — `src/pair_harness/adapters/audio/demo.py`
- **Path** (6 connections)
- **test_arbitrary_chunk_sizes_are_stitched()** (6 connections) — `tests/unit/test_vad_state.py`
- **test_rechunks_20ms_blocks_into_512_sample_frames()** (6 connections) — `tests/unit/test_vad_state.py`
- **copy_reference_model()** (5 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **.__init__()** (5 connections) — `src/pair_harness/core/voice_runtime.py`
- **._load_session()** (4 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **test_default_redemption_window_keeps_short_pause_inside_turn()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_missing_model_raises_unavailable()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_short_burst_is_false_trigger()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_speech_ended_after_redemption_silence()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_stream_end_with_open_speech_emits_ended()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_voice_resumes_within_redemption_window()** (4 connections) — `tests/unit/test_vad_state.py`
- **Path** (3 connections)
- **.detect()** (3 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- *... and 29 more nodes in this community*

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (6 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (5 shared connections)
- [Demo 语音合成](Demo_语音合成.md) (4 shared connections)
- [委派与契约模型](委派与契约模型.md) (4 shared connections)
- [语音播放与采集控制](语音播放与采集控制.md) (4 shared connections)
- [语音运行时测试](语音运行时测试.md) (2 shared connections)
- [语音播放队列](语音播放队列.md) (1 shared connections)
- [adapters: DemoSpeechRecogniz…](adapters-_DemoSpeechRecogniz….md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/demo.py`
- `src/pair_harness/adapters/audio/silero_vad.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `src/pair_harness/core/voice_runtime.py`
- `tests/unit/test_vad_state.py`
- `tests/unit/test_voice_runtime.py`

## Audit Trail

- EXTRACTED: 117 (91%)
- INFERRED: 11 (9%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*