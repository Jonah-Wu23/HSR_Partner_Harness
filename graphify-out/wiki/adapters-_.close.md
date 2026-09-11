# adapters: .close()

> 8 nodes · cohesion 0.25

## Key Concepts

- **MicrophoneCapture** (10 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.close()** (4 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.__aexit__()** (2 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.chunks()** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.close()** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **停止播放线程并关闭输出流（shutdown 时调用）。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **采集 16 kHz 单声道 int16 PCM 的麦克风流。 Windows 的 MME 默认输入设备经常拒绝 16 kHz 或阻塞式输入；这里优先…** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`

## Relationships

- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (3 shared connections)
- [adapters: OutputStream](adapters-_OutputStream.md) (2 shared connections)
- [adapters: sounddevice_io.py](adapters-_sounddevice_io.py.md) (2 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/sounddevice_io.py`

## Audit Trail

- EXTRACTED: 14 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*