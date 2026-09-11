# adapters: qwen_voice_customi…

> 12 nodes · cohesion 0.21

## Key Concepts

- **qwen_voice_customization.py** (17 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **build_clone_payload()** (8 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **build_design_payload()** (7 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **normalize_prefix()** (7 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **Any** (4 connections)
- **test_build_clone_payload_shape()** (2 connections) — `tests/unit/test_voice_cli.py`
- **test_build_design_payload_voice_enrollment_form()** (2 connections) — `tests/unit/test_voice_cli.py`
- **Qwen-Audio-TTS 音色 customization 客户端（V0.3.2 M6）。 供…** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **固定声音设计 payload：与复刻同一 customization 契约，改传描述文本。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **校验并规范 prefix：只允许小写字母/数字，最长 10 字符。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **固定复刻 payload，支持服务端 URL 与本地音频 data URI。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **_urllib_post_json()** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`

## Relationships

- [adapters: customization_endp…](adapters-_customization_endp….md) (6 shared connections)
- [音色 CLI 测试](音色_CLI_测试.md) (5 shared connections)
- [adapters: PostJson](adapters-_PostJson.md) (5 shared connections)
- [音色创建 CLI](音色创建_CLI.md) (3 shared connections)
- [test_v032_m6_voice.py: test_v032_m6_voice…](test_v032_m6_voice.py-_test_v032_m6_voice….md) (2 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (1 shared connections)
- [千问语音合成适配器](千问语音合成适配器.md) (1 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- `tests/unit/test_voice_cli.py`

## Audit Trail

- EXTRACTED: 38 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*