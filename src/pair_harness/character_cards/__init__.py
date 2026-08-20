"""角色卡纯编解码模块（V0.4.0 逻辑底座，与 V0.3.2 并行隔离开发）。

对外入口：

- :func:`load_card_json` / :func:`load_card_payload`：v2/v3 JSON 导入；
- :func:`dump_card_v3`：v3 JSON 导出；
- :func:`read_png_card` / :func:`write_png_card`：PNG 元数据读写与头像保留；
- :class:`CharacterCardState` / :class:`CharacterVoiceState`：界面状态枚举。

本包不依赖 SQLite、Sidecar 请求、React 状态或当前配对系统；
不做语义猜测，不执行导入内容，不掩盖失败。
"""

from pair_harness.character_cards.codec import (
    CardImportError,
    CompatReport,
    ImportResult,
    dump_card_v3,
    load_card_json,
    load_card_payload,
)
from pair_harness.character_cards.models import (
    FIXED_ASR_MODEL,
    FIXED_TTS_MODEL,
    AvatarAsset,
    CharacterBook,
    CharacterCard,
    HsrExtension,
    VoiceProfile,
    WorldBookEntry,
)
from pair_harness.character_cards.png import PngCardError, read_png_card, write_png_card
from pair_harness.character_cards.states import (
    CARD_STATES,
    VOICE_STATES,
    CharacterCardState,
    CharacterVoiceState,
)

__all__ = [
    "CARD_STATES",
    "VOICE_STATES",
    "AvatarAsset",
    "CardImportError",
    "CharacterBook",
    "CharacterCard",
    "CharacterCardState",
    "CharacterVoiceState",
    "CompatReport",
    "FIXED_ASR_MODEL",
    "FIXED_TTS_MODEL",
    "HsrExtension",
    "ImportResult",
    "PngCardError",
    "VoiceProfile",
    "WorldBookEntry",
    "dump_card_v3",
    "load_card_json",
    "load_card_payload",
    "read_png_card",
    "write_png_card",
]
