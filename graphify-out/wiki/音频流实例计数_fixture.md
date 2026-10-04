# 音频流实例计数 fixture

> 3 nodes · cohesion 0.67

## Key Concepts

- **_fresh_streams()** (3 connections) — `tests/unit/test_sounddevice_io.py`
- **fixture** (1 connections)
- **每个用例独立统计创建的流实例；用例对替身模块的替换经 monkeypatch 还原。** (1 connections) — `tests/unit/test_sounddevice_io.py`

## Relationships

- [音频输出流测试](音频输出流测试.md) (1 shared connections)

## Source Files

- `tests/unit/test_sounddevice_io.py`

## Audit Trail

- EXTRACTED: 3 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*