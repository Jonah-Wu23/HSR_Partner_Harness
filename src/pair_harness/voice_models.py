"""V0.3.2 M6：语音模型不可变产品常量（计划 5.17 节）。

- ASR 固定 ``qwen-audio-3.0-asr-flash-streaming``。
- TTS、5 次声音复刻和古代机械声音设计的 ``target_model`` 固定
  ``qwen-audio-3.0-tts-flash``。

用户侧（前端表单、JSONL 命令参数、SQLite 账号配置、环境变量覆盖、
``.env.example``）一律不提供模型修改入口。后续如确需换模型，必须作为
新的正式版本修改代码、文档、音色生成并完成真实联调，不能让用户在
设置页临时切换。
"""

from __future__ import annotations

from typing import Final

VOICE_ASR_MODEL: Final = "qwen-audio-3.0-asr-flash-streaming"
VOICE_TTS_MODEL: Final = "qwen-audio-3.0-tts-flash"

# Qwen-Audio-TTS 音色 customization 创建契约（docs/design/千问声音复刻文档.md）：
# model=voice-enrollment + input.action=create_voice + input.target_model 固定值。
# Qwen3-TTS 系列的 qwen-voice-enrollment / action=create / input.audio.data
# 属于另一模型系列的 payload，禁止挪用到本链路。
VOICE_ENROLLMENT_MODEL: Final = "voice-enrollment"
VOICE_ENROLLMENT_ACTION: Final = "create_voice"
