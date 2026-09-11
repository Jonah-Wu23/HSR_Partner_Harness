# adapters: OutputStream

> 18 nodes · cohesion 0.16

## Key Concepts

- **AudioPlayer** (23 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **._play()** (5 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **._close_stream()** (4 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **._ensure_stream()** (4 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **._ensure_stream_locked()** (4 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **._close_stream_locked()** (3 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.play_blocking()** (3 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.stop()** (3 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **OutputStream** (2 connections)
- **._run()** (2 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.start()** (2 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.wait_until_idle()** (2 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **长生命周期输出流播放器（V0.2 M2-4：连续音频输出流）。 持有单一 sounddevice.OutputStream，惰性创建、设备异常/被 stop…** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **立即停止播放：清空缓冲、丢弃在途块并关闭流（流下次重建）。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **把一块 PCM 写入缓冲；缓冲满时阻塞等待（防止 TTS 超速）。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **写流并按块时长近似节奏播放；设备异常时重建流，不中断线程。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **惰性创建输出流；创建失败返回 None（本块静默丢弃，下块重试）。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`

## Relationships

- [test_sounddevice_io.py: test_sounddevice_i…](test_sounddevice_io.py-_test_sounddevice_i….md) (6 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (3 shared connections)
- [adapters: .close()](adapters-_.close.md) (2 shared connections)
- [adapters: sounddevice_io.py](adapters-_sounddevice_io.py.md) (1 shared connections)
- [语音播放与采集控制](语音播放与采集控制.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/sounddevice_io.py`

## Audit Trail

- EXTRACTED: 31 (82%)
- INFERRED: 7 (18%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*