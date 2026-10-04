# VAD 分帧与状态机测试

> 18 nodes · cohesion 0.19

## Key Concepts

- **test_vad_state.py** (10 connections) — `tests/unit/test_vad_state.py`
- **_collect()** (8 connections) — `tests/unit/test_vad_state.py`
- **FakeSession** (7 connections) — `tests/unit/test_vad_state.py`
- **_make_detector()** (7 connections) — `tests/unit/test_vad_state.py`
- **test_arbitrary_chunk_sizes_are_stitched()** (6 connections) — `tests/unit/test_vad_state.py`
- **test_rechunks_20ms_blocks_into_512_sample_frames()** (6 connections) — `tests/unit/test_vad_state.py`
- **Path** (4 connections)
- **test_speech_segment_state_machine()** (4 connections) — `tests/unit/test_vad_state.py`
- **test_empty_chunks_are_skipped()** (3 connections) — `tests/unit/test_vad_state.py`
- **test_missing_model_raises_onnxruntime_error()** (3 connections) — `tests/unit/test_vad_state.py`
- **_stream()** (1 connections) — `tests/unit/test_vad_state.py`
- **.__init__()** (1 connections) — `tests/unit/test_vad_state.py`
- **.run()** (1 connections) — `tests/unit/test_vad_state.py`
- **MonkeyPatch** (1 connections)
- **parametrize** (1 connections)
- **20 ms（512 字节）块被重分帧：3 块凑 1.5 帧，跨块拼接。** (1 connections) — `tests/unit/test_vad_state.py`
- **不规则块大小（如 999 字节）也能正确拼接成帧。** (1 connections) — `tests/unit/test_vad_state.py`
- **模拟 onnxruntime InferenceSession：按序吐出注入的概率。** (1 connections) — `tests/unit/test_vad_state.py`

## Relationships

- [Silero VAD 语音检测](Silero_VAD_语音检测.md) (7 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (1 shared connections)

## Source Files

- `tests/unit/test_vad_state.py`

## Audit Trail

- EXTRACTED: 35 (95%)
- INFERRED: 2 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*