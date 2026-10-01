from __future__ import annotations

from enum import Enum


class CharacterVoiceState(str, Enum):
    """角色卡音色绑定状态。

    - ``voice_unconfigured``：尚未配置参考音频或声音描述。
    - ``voice_creating``：已向 DashScope 提交创建请求，等待结果。
    - ``voice_ready``：创建成功并保存了 ``voice_id``。
    - ``voice_failed``：创建失败，保留供应商原始错误。
    """

    UNCONFIGURED = "voice_unconfigured"
    CREATING = "voice_creating"
    READY = "voice_ready"
    FAILED = "voice_failed"
