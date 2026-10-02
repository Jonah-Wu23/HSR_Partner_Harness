# 参考音色 manifest 加载与校验。config/voices/reference_voice_manifest.json 记录 6 个说话方的
# speaker_id、安装包内素材路径、可选公开 URL、prefix 与固定 target_model；复刻时把安装包内
# 音频转为 data URI 提交，公开 URL 只作素材来源记录。结构不符或素材缺失时抛 VoiceManifestError。

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from pair_harness.config.pairs import list_pair_configs, repository_root
from pair_harness.voice_models import VOICE_TTS_MODEL

MANIFEST_RELATIVE_PATH = Path("config") / "voices" / "reference_voice_manifest.json"

# 固定执行顺序：5 个复刻 + 1 个设计
REFERENCE_SPEAKER_ORDER: tuple[str, ...] = (
    "phainon",
    "firefly",
    "sam",
    "march7",
    "fourth_mirror",
    "ancient_machine",
)
DESIGN_SPEAKER_IDS = frozenset({"ancient_machine"})

# 古代机械声音设计固定试听文本（与 scripts/create_qwen_voice.py 的真实
# 生成流程一致；改文本视为换音色素材，需按正式版本处理）
ANCIENT_MACHINE_PREVIEW_TEXT = "你好，我是神秘的古代机械。核心模块已启动，正在等待指令。"


def assistant_speaker_ids(*, root: Path | None = None) -> frozenset[str]:
    """从配对目录推导全部助手侧说话方 id 集合。

    助手不使用 TTS。provision 与 preview 对助手侧说话方的拒绝判定以此集合
    为唯一依据；说话方随 ``config/pairs/*.yaml`` 的 ``assistant.id`` 推导，
    代码里不硬编码名单。
    """
    return frozenset(pair.assistant.id for pair in list_pair_configs(root=root))


class VoiceManifestError(RuntimeError):
    """manifest 缺失、结构不符或本地素材文件缺失。"""


class ReferenceVoiceEntry(BaseModel):
    """manifest 中的一个说话方。``local_path`` 在加载后是安装包内的绝对路径。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    speaker_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    method: Literal["clone", "design"]
    local_path: Path
    # 复刻项为空或 HTTP(S) 地址；声音设计项必须为空。
    public_url: str = Field(pattern=r"^(https?://.+)?$")
    prefix: str = Field(pattern=r"^[a-z0-9]{1,10}$")
    target_model: str

    @field_validator("target_model")
    @classmethod
    def _check_target_model(cls, value: str) -> str:
        if value != VOICE_TTS_MODEL:
            raise ValueError(f"target_model 必须固定为 {VOICE_TTS_MODEL}，得到 {value!r}")
        return value

    @model_validator(mode="after")
    def _check_method(self) -> ReferenceVoiceEntry:
        if (self.method == "design") != (self.speaker_id in DESIGN_SPEAKER_IDS):
            raise ValueError(
                f"{self.speaker_id}: 声音设计项固定为 ancient_machine，"
                f"与 method={self.method} 不一致"
            )
        if self.method == "design" and self.public_url:
            raise ValueError(f"{self.speaker_id}: 声音设计项不使用 public_url")
        return self

    @property
    def profile_key(self) -> str:
        """账号级音色映射键（provider_configs）。"""
        return f"voice.profile.{self.speaker_id}.voice_id"


class _ReferenceVoiceManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    comment: str = Field(default="", alias="_comment")
    speakers: tuple[ReferenceVoiceEntry, ...]

    @model_validator(mode="after")
    def _check_speakers(self) -> _ReferenceVoiceManifest:
        speaker_ids = tuple(entry.speaker_id for entry in self.speakers)
        if speaker_ids != REFERENCE_SPEAKER_ORDER:
            raise ValueError(
                f"speaker 顺序或集合不符，期望 {REFERENCE_SPEAKER_ORDER}，实际 {speaker_ids}"
            )
        prefixes = [entry.prefix for entry in self.speakers]
        if len(set(prefixes)) != len(prefixes):
            raise ValueError(f"prefix 重复: {prefixes}")
        return self


def load_reference_voice_manifest(
    root: Path | None = None,
) -> tuple[ReferenceVoiceEntry, ...]:
    base = root or repository_root()
    path = base / MANIFEST_RELATIVE_PATH
    if not path.is_file():
        raise VoiceManifestError(f"参考音色 manifest 不存在: {path}")
    try:
        manifest = _ReferenceVoiceManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except ValidationError as exc:
        raise VoiceManifestError(f"参考音色 manifest 不合法: {path}: {exc}") from exc
    entries = tuple(
        entry.model_copy(update={"local_path": base / entry.local_path})
        for entry in manifest.speakers
    )
    for entry in entries:
        if not entry.local_path.is_file():
            raise VoiceManifestError(
                f"{entry.speaker_id}: 本地素材不存在: {entry.local_path}"
            )
    return entries
