# 音色创建 CLI

> 23 nodes · cohesion 0.17

## Key Concepts

- **create_qwen_voice.py** (18 connections) — `scripts/create_qwen_voice.py`
- **VoiceCliError** (10 connections) — `scripts/create_qwen_voice.py`
- **cmd_clone()** (8 connections) — `scripts/create_qwen_voice.py`
- **cmd_design()** (8 connections) — `scripts/create_qwen_voice.py`
- **_client()** (7 connections) — `scripts/create_qwen_voice.py`
- **build_parser()** (6 connections) — `scripts/create_qwen_voice.py`
- **cmd_adopt()** (5 connections) — `scripts/create_qwen_voice.py`
- **Path** (5 connections)
- **concat_wavs()** (4 connections) — `scripts/create_qwen_voice.py`
- **data_uri_for()** (4 connections) — `scripts/create_qwen_voice.py`
- **_api_key()** (3 connections) — `scripts/create_qwen_voice.py`
- **_load_dotenv()** (3 connections) — `scripts/create_qwen_voice.py`
- **main()** (3 connections) — `scripts/create_qwen_voice.py`
- **pick_longest_wav()** (3 connections) — `scripts/create_qwen_voice.py`
- **Namespace** (3 connections)
- **save_preview_audio()** (3 connections) — `scripts/create_qwen_voice.py`
- **ArgumentParser** (1 connections)
- **RuntimeError** (1 connections)
- **拼接多个 WAV（要求参数一致：声道数/采样宽度/采样率），段间插入静音。** (1 connections) — `scripts/create_qwen_voice.py`
- **创建 Qwen 音色并写回 pair 配置（V0.3.2 M6 起复用共享 customization 客户端）。 子命令： clone ——…** (1 connections) — `scripts/create_qwen_voice.py`
- **轻量加载项目 .env（KEY=VALUE，跳过注释），不覆盖已存在的环境变量。** (1 connections) — `scripts/create_qwen_voice.py`
- **CLI 可预期错误（缺少 Key、HTTP 失败、配置缺失等）。** (1 connections) — `scripts/create_qwen_voice.py`
- **向后兼容的 CLI 辅助入口，实际实现与桌面端共用。** (1 connections) — `scripts/create_qwen_voice.py`

## Relationships

- [adapters: PostJson](adapters-_PostJson.md) (5 shared connections)
- [adapters: qwen_voice_customi…](adapters-_qwen_voice_customi….md) (3 shared connections)
- [复现脚本与 ACP 链路](复现脚本与_ACP_链路.md) (2 shared connections)
- [test_pair_config.py: adopt_voice_id()](test_pair_config.py-_adopt_voice_id.md) (2 shared connections)
- [千问语音合成适配器](千问语音合成适配器.md) (1 shared connections)
- [adapters: customization_endp…](adapters-_customization_endp….md) (1 shared connections)

## Source Files

- `scripts/create_qwen_voice.py`

## Audit Trail

- EXTRACTED: 50 (88%)
- INFERRED: 7 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*