# sounddevice 流异常测试

> 7 nodes · cohesion 0.29

## Key Concepts

- **test_capture_callback_error_reaches_chunks_consumer()** (8 connections) — `tests/unit/test_sounddevice_io.py`
- **MonkeyPatch** (1 connections)
- **输入回调出错时中止输入流，chunks() 的消费者收到该异常并结束。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **close()** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **__init__()** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **start()** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **stop()** (1 connections) — `tests/unit/test_sounddevice_io.py`

## Relationships

- [音频输出流测试](音频输出流测试.md) (1 shared connections)
- [麦克风采集与重采样](麦克风采集与重采样.md) (1 shared connections)

## Source Files

- `tests/unit/test_sounddevice_io.py`

## Audit Trail

- EXTRACTED: 7 (88%)
- INFERRED: 1 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*