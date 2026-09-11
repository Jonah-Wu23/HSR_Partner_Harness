# adapters: sounddevice_io.py

> 14 nodes · cohesion 0.15

## Key Concepts

- **sounddevice_io.py** (7 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **_input_device_candidates()** (5 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **_resample_input()** (4 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **.__aenter__()** (3 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **test_input_device_candidates_defaults_to_none_when_no_default()** (3 connections) — `tests/unit/test_sounddevice_io.py`
- **test_input_device_candidates_prefers_wdm_ks_microphone()** (3 connections) — `tests/unit/test_sounddevice_io.py`
- **test_resample_input_downmixes_stereo_and_resamples()** (3 connections) — `tests/unit/test_sounddevice_io.py`
- **callback()** (2 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **list_devices()** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **返回默认输入及可尝试的真实麦克风设备，优先 Windows WDM-KS。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **把 RawInputStream 的 int16 帧降为目标采样率的单声道 PCM。** (1 connections) — `src/pair_harness/adapters/audio/sounddevice_io.py`
- **F7/兼容：输入设备候选——默认设备居首、WDM-KS 麦克风优先。 覆盖 ``_input_device_candidates``（Windows…** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **默认输入不可用时回退 None（只列候选），不抛错。** (1 connections) — `tests/unit/test_sounddevice_io.py`
- **F7/兼容：int16 帧降混 + 重采样（``_resample_input`` 核心路径）。** (1 connections) — `tests/unit/test_sounddevice_io.py`

## Relationships

- [test_sounddevice_io.py: test_sounddevice_i…](test_sounddevice_io.py-_test_sounddevice_i….md) (4 shared connections)
- [adapters: .close()](adapters-_.close.md) (2 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [adapters: OutputStream](adapters-_OutputStream.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/sounddevice_io.py`
- `tests/unit/test_sounddevice_io.py`

## Audit Trail

- EXTRACTED: 21 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*