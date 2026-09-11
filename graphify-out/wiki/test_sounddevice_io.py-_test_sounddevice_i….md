# test_sounddevice_io.py: test_sounddevice_i…

> 19 nodes · cohesion 0.20

## Key Concepts

- **test_sounddevice_io.py** (16 connections) — `tests/unit/test_sounddevice_io.py`
- **test_stop_clears_buffer_immediately_and_rebuilds_stream()** (9 connections) — `tests/unit/test_sounddevice_io.py`
- **_chunk()** (8 connections) — `tests/unit/test_sounddevice_io.py`
- **_wait_stream()** (8 connections) — `tests/unit/test_sounddevice_io.py`
- **test_bounded_buffer_throttles_fast_producer()** (7 connections) — `tests/unit/test_sounddevice_io.py`
- **_wait_writes()** (7 connections) — `tests/unit/test_sounddevice_io.py`
- **test_empty_pcm_blocks_are_ignored()** (6 connections) — `tests/unit/test_sounddevice_io.py`
- **test_single_stream_reused_across_chunks_and_idle_gaps()** (6 connections) — `tests/unit/test_sounddevice_io.py`
- **test_stream_created_lazily_on_first_chunk()** (6 connections) — `tests/unit/test_sounddevice_io.py`
- **test_play_blocking_after_close_is_noop()** (4 connections) — `tests/unit/test_sounddevice_io.py`
- **AudioPlayer 长生命周期输出流测试（V0.2 M2-4）。 以假 sounddevice 模块驱动播放器，不触真实音频设备：验证输出流…** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **输出流惰性创建：线程空闲时不建流，首块写入才创建。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **缓冲上限钳制生产节奏：慢消费下批量入队被阻塞，且不丢块。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **stop 立即清空缓冲并关闭流（丢弃积压）；下次播放惰性重建新流。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **shutdown 后写入为无操作：不抛错、不重启线程、不建流。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **空 PCM 块（final 标记）不写入缓冲。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **ms 毫秒 @ 16 kHz 单声道 int16 的静音块。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **等待播放线程惰性创建第 index 个流（建流在消费线程中异步发生）。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **块间间隙与空闲等待不关闭流：全程单一 OutputStream。** (1 connections) — `tests/unit/test_sounddevice_io.py`

## Relationships

- [test_sounddevice_io.py: FakeOutputStream](test_sounddevice_io.py-_FakeOutputStream.md) (7 shared connections)
- [adapters: OutputStream](adapters-_OutputStream.md) (6 shared connections)
- [adapters: sounddevice_io.py](adapters-_sounddevice_io.py.md) (4 shared connections)
- [test_sounddevice_io.py: _fresh_streams()](test_sounddevice_io.py-__fresh_streams.md) (1 shared connections)

## Source Files

- `tests/unit/test_sounddevice_io.py`

## Audit Trail

- EXTRACTED: 46 (88%)
- INFERRED: 6 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*