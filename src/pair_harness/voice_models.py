# 语音模型是不可变产品常量：ASR、TTS 与声音复刻、声音设计的 target_model 都固定在这里，
# 前端、JSONL 命令、账号配置与环境变量都不提供修改入口。换模型需要重新生成音色并发布新版本。

from __future__ import annotations

from typing import Final

VOICE_ASR_MODEL: Final = "qwen-audio-3.0-asr-flash-streaming"
VOICE_TTS_MODEL: Final = "qwen-audio-3.0-tts-flash"

# Qwen-Audio-TTS 音色 customization 创建契约（docs/design/dashscope/千问声音复刻文档.md）：
# model=voice-enrollment + input.action=create_voice + input.target_model 固定值。
# Qwen3-TTS 系列的 qwen-voice-enrollment / action=create / input.audio.data
# 属于另一模型系列的 payload，禁止挪用到本链路。
VOICE_ENROLLMENT_MODEL: Final = "voice-enrollment"
VOICE_ENROLLMENT_ACTION: Final = "create_voice"
