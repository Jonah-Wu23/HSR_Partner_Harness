# adapters: customization_endp…

> 13 nodes · cohesion 0.24

## Key Concepts

- **QwenVoiceCustomizationClient** (17 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **._request()** (9 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **CustomizationResult** (8 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **.create_designed_voice()** (5 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **.create_cloned_voice()** (4 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **._redacted_error()** (4 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **._redact()** (3 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **customization_endpoint()** (2 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **.endpoint()** (2 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **fake_clone()** (2 connections) — `tests/unit/test_application_service.py`
- **fake_design()** (2 connections) — `tests/unit/test_application_service.py`
- **Qwen-Audio-TTS 音色 customization 客户端（同步 urllib，可注入传输）。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **创建成功的结果：真实响应中的 voice_id 与原始 payload。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`

## Relationships

- [adapters: qwen_voice_customi…](adapters-_qwen_voice_customi….md) (6 shared connections)
- [Demo 服务与队列测试](Demo_服务与队列测试.md) (4 shared connections)
- [adapters: PostJson](adapters-_PostJson.md) (4 shared connections)
- [音色绑定与参考音](音色绑定与参考音.md) (2 shared connections)
- [test_v032_m6_voice.py: test_v032_m6_voice…](test_v032_m6_voice.py-_test_v032_m6_voice….md) (2 shared connections)
- [音色创建 CLI](音色创建_CLI.md) (1 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (1 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)
- [音色 CLI 测试](音色_CLI_测试.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- `tests/unit/test_application_service.py`

## Audit Trail

- EXTRACTED: 34 (83%)
- INFERRED: 7 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*