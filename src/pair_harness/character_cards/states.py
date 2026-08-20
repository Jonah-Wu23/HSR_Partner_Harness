"""角色卡对外状态枚举（V0.4.0 逻辑底座冻结契约）。

两组状态相互正交：

- :class:`CharacterCardState` 描述角色卡本体在库中的生命周期；
- :class:`CharacterVoiceState` 描述角色卡绑定音色的创建状态。

强视觉 AI 的界面只消费这两个枚举与配套样例数据，不依赖
SQLite、Sidecar 协议或当前配对系统。状态由业务层根据真实
结果赋值；导入失败、音色创建失败必须如实落在 ``invalid`` /
``voice_failed``，不得用兜底数据改写。
"""

from __future__ import annotations

from enum import Enum


class CharacterCardState(str, Enum):
    """角色卡生命周期状态。

    - ``draft``：新建或导入前的草稿，尚未持久化。
    - ``saved``：已保存到本地角色库（含新建后保存与编辑后保存）。
    - ``imported``：从酒馆 JSON/PNG 导入并完成落库的卡。
    - ``invalid``：导入解析失败或数据被判定非法；保留原始错误。
    """

    DRAFT = "draft"
    SAVED = "saved"
    IMPORTED = "imported"
    INVALID = "invalid"


class CharacterVoiceState(str, Enum):
    """角色卡音色绑定状态。

    - ``voice_unconfigured``：尚未配置参考音频/声音描述，未发起创建。
    - ``voice_creating``：已向 DashScope 提交创建请求，等待真实结果。
    - ``voice_ready``：创建成功并保存了真实 ``voice_id``。
    - ``voice_failed``：创建失败；保留供应商原始错误供界面展示。
    """

    UNCONFIGURED = "voice_unconfigured"
    CREATING = "voice_creating"
    READY = "voice_ready"
    FAILED = "voice_failed"


CARD_STATES: tuple[str, ...] = tuple(state.value for state in CharacterCardState)
VOICE_STATES: tuple[str, ...] = tuple(state.value for state in CharacterVoiceState)
