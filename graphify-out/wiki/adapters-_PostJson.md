# adapters: PostJson

> 10 nodes · cohesion 0.24

## Key Concepts

- **VoiceCustomizationError** (26 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **audio_file_to_data_uri()** (10 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **.__init__()** (4 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **test_clone_payload_accepts_remote_and_local_data_uri()** (4 connections) — `tests/unit/test_v032_m6_voice.py`
- **.__init__()** (2 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **PostJson** (1 connections)
- **Path** (1 connections)
- **RuntimeError** (1 connections)
- **把本地 WAV/MP3/M4A 转为已实测可用的 ``input.url`` data URI。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- **customization 请求失败；保留真实 HTTP 状态与 DashScope 错误信息。** (1 connections) — `src/pair_harness/adapters/audio/qwen_voice_customization.py`

## Relationships

- [音色创建 CLI](音色创建_CLI.md) (5 shared connections)
- [adapters: qwen_voice_customi…](adapters-_qwen_voice_customi….md) (5 shared connections)
- [音色 CLI 测试](音色_CLI_测试.md) (5 shared connections)
- [adapters: customization_endp…](adapters-_customization_endp….md) (4 shared connections)
- [音色绑定与参考音](音色绑定与参考音.md) (3 shared connections)
- [test_v032_m6_voice.py: test_v032_m6_voice…](test_v032_m6_voice.py-_test_v032_m6_voice….md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [V0.3.5 接线测试](V0.3.5_接线测试.md) (1 shared connections)
- [桌面后端应用服务](桌面后端应用服务.md) (1 shared connections)

## Source Files

- `src/pair_harness/adapters/audio/qwen_voice_customization.py`
- `tests/unit/test_v032_m6_voice.py`

## Audit Trail

- EXTRACTED: 29 (72%)
- INFERRED: 11 (28%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*