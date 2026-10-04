# Silero VAD 语音检测

> 13 nodes · cohesion 0.26

## Key Concepts

- **SileroVoiceActivityDetector** (15 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **VadEvent** (14 connections) — `src/pair_harness/core/contracts.py`
- **VoiceActivityDetector** (9 connections) — `src/pair_harness/core/ports.py`
- **silero_vad.py** (6 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **._load_session()** (4 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **.detect()** (3 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **.__init__()** (3 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **Path** (2 connections)
- **._frame_probability()** (2 connections) — `src/pair_harness/adapters/audio/silero_vad.py`
- **.detect()** (2 connections) — `src/pair_harness/core/ports.py`
- **.detect()** (2 connections) — `tests/voice_helpers.py`
- **InferenceSession** (1 connections)
- **本地 Silero VAD v5 状态机。 ``detect`` 每次调用维护独立的模型循环状态；进入即产出…** (1 connections) — `src/pair_harness/adapters/audio/silero_vad.py`

## Relationships

- [VAD 分帧与状态机测试](VAD_分帧与状态机测试.md) (7 shared connections)
- [千问语音合成与识别](千问语音合成与识别.md) (6 shared connections)
- [ACP 编程引擎适配器](ACP_编程引擎适配器.md) (3 shared connections)
- [语音上下行协调器](语音上下行协调器.md) (3 shared connections)
- [语音运行时装配与中继](语音运行时装配与中继.md) (2 shared connections)
- [语音播放与 VAD 测试](语音播放与_VAD_测试.md) (2 shared connections)
- [审批裁决与审查智能体](审批裁决与审查智能体.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/silero_vad.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `tests/voice_helpers.py`

## Audit Trail

- EXTRACTED: 37 (84%)
- INFERRED: 7 (16%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*