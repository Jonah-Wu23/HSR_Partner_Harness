# adapters: DemoSpeechRecogniz…

> 12 nodes · cohesion 0.23

## Key Concepts

- **AsrEvent** (24 connections) — `src/pair_harness/core/contracts.py`
- **SpeechRecognizer** (12 connections) — `src/pair_harness/core/ports.py`
- **RecognizerPort** (6 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **DemoSpeechRecognizer** (5 connections) — `src/pair_harness/adapters/audio/demo.py`
- **.stream_transcribe()** (2 connections) — `src/pair_harness/adapters/audio/demo.py`
- **.stream_transcribe()** (2 connections) — `src/pair_harness/core/ports.py`
- **.stream_transcribe()** (2 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`
- **.stream_transcribe()** (2 connections) — `tests/unit/test_mobile_audio.py`
- **.stream_transcribe()** (2 connections) — `tests/unit/test_voice_runtime.py`
- **.__init__()** (1 connections) — `src/pair_harness/adapters/audio/demo.py`
- **Protocol** (1 connections)
- **与 ``qwen_asr.QwenStreamingRecognizer`` 真实接口对齐的端口。…** (1 connections) — `src/pair_harness/desktop_backend/mobile_audio.py`

## Relationships

- [移动端音频与 ASR 会话](移动端音频与_ASR_会话.md) (7 shared connections)
- [ACP 编码引擎](ACP_编码引擎.md) (4 shared connections)
- [Demo 语音合成](Demo_语音合成.md) (3 shared connections)
- [千问流式语音识别](千问流式语音识别.md) (3 shared connections)
- [语音播放与采集控制](语音播放与采集控制.md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [委派与契约模型](委派与契约模型.md) (2 shared connections)
- [千问流式识别测试](千问流式识别测试.md) (2 shared connections)
- [语音运行时测试](语音运行时测试.md) (2 shared connections)
- [千问音频实网测试](千问音频实网测试.md) (1 shared connections)
- [Silero VAD 语音活动检测](Silero_VAD_语音活动检测.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/demo.py`
- `src/pair_harness/core/contracts.py`
- `src/pair_harness/core/ports.py`
- `src/pair_harness/desktop_backend/mobile_audio.py`
- `tests/unit/test_mobile_audio.py`
- `tests/unit/test_voice_runtime.py`

## Audit Trail

- EXTRACTED: 34 (76%)
- INFERRED: 11 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*